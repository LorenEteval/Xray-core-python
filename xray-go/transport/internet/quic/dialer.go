package quic

import (
	"context"
	"sync"
	"time"

	"github.com/quic-go/quic-go"
	"github.com/quic-go/quic-go/logging"
	"github.com/quic-go/quic-go/qlog"
	"github.com/xtls/xray-core/common"
	"github.com/xtls/xray-core/common/errors"
	"github.com/xtls/xray-core/common/net"
	"github.com/xtls/xray-core/common/task"
	"github.com/xtls/xray-core/transport/internet"
	"github.com/xtls/xray-core/transport/internet/stat"
	"github.com/xtls/xray-core/transport/internet/tls"
)

type connectionContext struct {
	rawConn *sysConn
	conn    quic.Connection
}

var errConnectionClosed = errors.New("connection closed")

func (c *connectionContext) openStream(destAddr net.Addr) (*interConn, error) {
	if !isActive(c.conn) {
		return nil, errConnectionClosed
	}

	stream, err := c.conn.OpenStream()
	if err != nil {
		return nil, err
	}

	conn := &interConn{
		stream: stream,
		local:  c.conn.LocalAddr(),
		remote: destAddr,
	}

	return conn, nil
}

type clientConnections struct {
	access  sync.Mutex
	conns   map[net.Destination][]*connectionContext
	cleanup *task.Periodic
}

func isActive(s quic.Connection) bool {
	select {
	case <-s.Context().Done():
		return false
	default:
		return true
	}
}

func removeInactiveConnections(conns []*connectionContext) []*connectionContext {
	activeConnections := make([]*connectionContext, 0, len(conns))
	for i, s := range conns {
		if isActive(s.conn) {
			activeConnections = append(activeConnections, s)
			continue
		}

		errors.LogInfo(context.Background(), "closing quic connection at index: ", i)
		if err := s.conn.CloseWithError(0, ""); err != nil {
			errors.LogInfoInner(context.Background(), err, "failed to close connection")
		}
		if err := s.rawConn.Close(); err != nil {
			errors.LogInfoInner(context.Background(), err, "failed to close raw connection")
		}
	}

	if len(activeConnections) < len(conns) {
		errors.LogInfo(context.Background(), "active quic connection reduced from ", len(conns), " to ", len(activeConnections))
		return activeConnections
	}

	return conns
}

func (s *clientConnections) cleanConnections() error {
	s.access.Lock()
	defer s.access.Unlock()

	if len(s.conns) == 0 {
		return nil
	}

	newConnMap := make(map[net.Destination][]*connectionContext)

	for dest, conns := range s.conns {
		conns = removeInactiveConnections(conns)
		if len(conns) > 0 {
			newConnMap[dest] = conns
		}
	}

	s.conns = newConnMap
	return nil
}

func (s *clientConnections) openConnection(ctx context.Context, destAddr net.Addr, config *Config, tlsConfig *tls.Config, sockopt *internet.SocketConfig) (stat.Connection, error) {
	s.access.Lock()
	defer s.access.Unlock()

	if s.conns == nil {
		s.conns = make(map[net.Destination][]*connectionContext)
	}

	dest := net.DestinationFromAddr(destAddr)

	var conns []*connectionContext
	if s, found := s.conns[dest]; found {
		conns = s
	}

	if len(conns) > 0 {
		s := conns[len(conns)-1]
		if isActive(s.conn) {
			conn, err := s.openStream(destAddr)
			if err == nil {
				return conn, nil
			}
			errors.LogInfoInner(ctx, err, "failed to openStream: ")
		} else {
			errors.LogInfo(ctx, "current quic connection is not active!")
		}
	}

	conns = removeInactiveConnections(conns)
	errors.LogInfo(ctx, "dialing quic to ", dest)
	rawConn, err := internet.DialSystem(ctx, dest, sockopt)
	if err != nil {
		return nil, errors.New("failed to dial to dest: ", err).AtWarning().Base(err)
	}

	quicConfig := &quic.Config{
		KeepAlivePeriod:      0,
		HandshakeIdleTimeout: time.Second * 8,
		MaxIdleTimeout:       time.Second * 300,
		Tracer: func(ctx context.Context, p logging.Perspective, ci quic.ConnectionID) *logging.ConnectionTracer {
			return qlog.NewConnectionTracer(&QlogWriter{connID: ci}, p, ci)
		},
	}

	var udpConn *net.UDPConn
	switch conn := rawConn.(type) {
	case *net.UDPConn:
		udpConn = conn
	case *internet.PacketConnWrapper:
		udpConn = conn.Conn.(*net.UDPConn)
	default:
		// TODO: Support sockopt for QUIC
		rawConn.Close()
		return nil, errors.New("QUIC with sockopt is unsupported").AtWarning()
	}

	sysConn, err := wrapSysConn(udpConn, config)
	if err != nil {
		rawConn.Close()
		return nil, err
	}
	tr := quic.Transport{
		ConnectionIDLength: 12,
		Conn:               sysConn,
	}
	conn, err := tr.Dial(context.Background(), destAddr, tlsConfig.GetTLSConfig(tls.WithDestination(dest)), quicConfig)
	if err != nil {
		sysConn.Close()
		return nil, err
	}

	context := &connectionContext{
		conn:    conn,
		rawConn: sysConn,
	}
	s.conns[dest] = append(conns, context)
	return context.openStream(destAddr)
}

var client clientConnections

func init() {
	client.conns = make(map[net.Destination][]*connectionContext)
	client.cleanup = &task.Periodic{
		Interval: time.Minute,
		Execute:  client.cleanConnections,
	}
	common.Must(client.cleanup.Start())
}

func Dial(ctx context.Context, dest net.Destination, streamSettings *internet.MemoryStreamConfig) (stat.Connection, error) {
	tlsConfig := tls.ConfigFromStreamSettings(streamSettings)
	if tlsConfig == nil {
		tlsConfig = &tls.Config{
			ServerName:    internalDomain,
			AllowInsecure: true,
		}
	}

	var destAddr *net.UDPAddr
	if dest.Address.Family().IsIP() {
		destAddr = &net.UDPAddr{
			IP:   dest.Address.IP(),
			Port: int(dest.Port),
		}
	} else {
		dialerIp := internet.DestIpAddress()
		if dialerIp != nil {
			destAddr = &net.UDPAddr{
				IP:   dialerIp,
				Port: int(dest.Port),
			}
			errors.LogInfo(ctx, "quic Dial use dialer dest addr: ", destAddr)
		} else {
			addr, err := net.ResolveUDPAddr("udp", dest.NetAddr())
			if err != nil {
				return nil, err
			}
			destAddr = addr
		}
	}

	config := streamSettings.ProtocolSettings.(*Config)

	return client.openConnection(ctx, destAddr, config, tlsConfig, streamSettings.SocketSettings)
}

func init() {
	common.Must(internet.RegisterTransportDialer(protocolName, Dial))
}
