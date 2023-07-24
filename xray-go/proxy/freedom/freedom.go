package freedom

//go:generate go run github.com/xtls/xray-core/common/errors/errorgen

import (
	"context"
	"crypto/rand"
	"encoding/binary"
	"io"
	"math/big"
	"time"

	"github.com/xtls/xray-core/common"
	"github.com/xtls/xray-core/common/buf"
	"github.com/xtls/xray-core/common/dice"
	"github.com/xtls/xray-core/common/errors"
	"github.com/xtls/xray-core/common/net"
	"github.com/xtls/xray-core/common/retry"
	"github.com/xtls/xray-core/common/session"
	"github.com/xtls/xray-core/common/signal"
	"github.com/xtls/xray-core/common/task"
	"github.com/xtls/xray-core/core"
	"github.com/xtls/xray-core/features/dns"
	"github.com/xtls/xray-core/features/policy"
	"github.com/xtls/xray-core/features/stats"
	"github.com/xtls/xray-core/transport"
	"github.com/xtls/xray-core/transport/internet"
	"github.com/xtls/xray-core/transport/internet/stat"
)

func init() {
	common.Must(common.RegisterConfig((*Config)(nil), func(ctx context.Context, config interface{}) (interface{}, error) {
		h := new(Handler)
		if err := core.RequireFeatures(ctx, func(pm policy.Manager, d dns.Client) error {
			return h.Init(config.(*Config), pm, d)
		}); err != nil {
			return nil, err
		}
		return h, nil
	}))
}

// Handler handles Freedom connections.
type Handler struct {
	policyManager policy.Manager
	dns           dns.Client
	config        *Config
}

// Init initializes the Handler with necessary parameters.
func (h *Handler) Init(config *Config, pm policy.Manager, d dns.Client) error {
	h.config = config
	h.policyManager = pm
	h.dns = d

	return nil
}

func (h *Handler) policy() policy.Session {
	p := h.policyManager.ForLevel(h.config.UserLevel)
	if h.config.Timeout > 0 && h.config.UserLevel == 0 {
		p.Timeouts.ConnectionIdle = time.Duration(h.config.Timeout) * time.Second
	}
	return p
}

func (h *Handler) resolveIP(ctx context.Context, domain string, localAddr net.Address) net.Address {
	var option dns.IPOption = dns.IPOption{
		IPv4Enable: true,
		IPv6Enable: true,
		FakeEnable: false,
	}
	if h.config.DomainStrategy == Config_USE_IP4 || (localAddr != nil && localAddr.Family().IsIPv4()) {
		option = dns.IPOption{
			IPv4Enable: true,
			IPv6Enable: false,
			FakeEnable: false,
		}
	} else if h.config.DomainStrategy == Config_USE_IP6 || (localAddr != nil && localAddr.Family().IsIPv6()) {
		option = dns.IPOption{
			IPv4Enable: false,
			IPv6Enable: true,
			FakeEnable: false,
		}
	}

	ips, err := h.dns.LookupIP(domain, option)
	if err != nil {
		newError("failed to get IP address for domain ", domain).Base(err).WriteToLog(session.ExportIDToError(ctx))
	}
	if len(ips) == 0 {
		return nil
	}
	return net.IPAddress(ips[dice.Roll(len(ips))])
}

func isValidAddress(addr *net.IPOrDomain) bool {
	if addr == nil {
		return false
	}

	a := addr.AsAddress()
	return a != net.AnyIP
}

// Process implements proxy.Outbound.
func (h *Handler) Process(ctx context.Context, link *transport.Link, dialer internet.Dialer) error {
	outbound := session.OutboundFromContext(ctx)
	if outbound == nil || !outbound.Target.IsValid() {
		return newError("target not specified.")
	}
	destination := outbound.Target
	UDPOverride := net.UDPDestination(nil, 0)
	if h.config.DestinationOverride != nil {
		server := h.config.DestinationOverride.Server
		if isValidAddress(server.Address) {
			destination.Address = server.Address.AsAddress()
			UDPOverride.Address = destination.Address
		}
		if server.Port != 0 {
			destination.Port = net.Port(server.Port)
			UDPOverride.Port = destination.Port
		}
	}

	input := link.Reader
	output := link.Writer

	var conn stat.Connection
	err := retry.ExponentialBackoff(5, 100).On(func() error {
		dialDest := destination
		if h.config.useIP() && dialDest.Address.Family().IsDomain() {
			ip := h.resolveIP(ctx, dialDest.Address.Domain(), dialer.Address())
			if ip != nil {
				dialDest = net.Destination{
					Network: dialDest.Network,
					Address: ip,
					Port:    dialDest.Port,
				}
				newError("dialing to ", dialDest).WriteToLog(session.ExportIDToError(ctx))
			}
		}

		rawConn, err := dialer.Dial(ctx, dialDest)
		if err != nil {
			return err
		}
		conn = rawConn
		return nil
	})
	if err != nil {
		return newError("failed to open connection to ", destination).Base(err)
	}
	defer conn.Close()
	newError("connection opened to ", destination, ", local endpoint ", conn.LocalAddr(), ", remote endpoint ", conn.RemoteAddr()).WriteToLog(session.ExportIDToError(ctx))

	var newCtx context.Context
	var newCancel context.CancelFunc
	if session.TimeoutOnlyFromContext(ctx) {
		newCtx, newCancel = context.WithCancel(context.Background())
	}

	plcy := h.policy()
	ctx, cancel := context.WithCancel(ctx)
	timer := signal.CancelAfterInactivity(ctx, func() {
		cancel()
		if newCancel != nil {
			newCancel()
		}
	}, plcy.Timeouts.ConnectionIdle)

	requestDone := func() error {
		defer timer.SetTimeout(plcy.Timeouts.DownlinkOnly)

		var writer buf.Writer
		if destination.Network == net.Network_TCP {
			if h.config.Fragment != nil {
				if h.config.Fragment.StartPacket == 0 && h.config.Fragment.EndPacket == 1 {
					newError("FRAGMENT", int(h.config.Fragment.MaxLength)).WriteToLog(session.ExportIDToError(ctx))
					writer = buf.NewWriter(
						&FragmentedClientHelloConn{
							Conn:        conn,
							maxLength:   int(h.config.Fragment.MaxLength),
							minInterval: time.Duration(h.config.Fragment.MinInterval) * time.Millisecond,
							maxInterval: time.Duration(h.config.Fragment.MaxInterval) * time.Millisecond,
						})
				} else {
					writer = buf.NewWriter(
						&FragmentWriter{
							Writer:      conn,
							minLength:   int(h.config.Fragment.MinLength),
							maxLength:   int(h.config.Fragment.MaxLength),
							minInterval: time.Duration(h.config.Fragment.MinInterval) * time.Millisecond,
							maxInterval: time.Duration(h.config.Fragment.MaxInterval) * time.Millisecond,
							startPacket: int(h.config.Fragment.StartPacket),
							endPacket:   int(h.config.Fragment.EndPacket),
							PacketCount: 0,
						})
				}
			} else {
				writer = buf.NewWriter(conn)
			}
		} else {
			writer = NewPacketWriter(conn, h, ctx, UDPOverride)
		}

		if err := buf.Copy(input, writer, buf.UpdateActivity(timer)); err != nil {
			return newError("failed to process request").Base(err)
		}

		return nil
	}

	responseDone := func() error {
		defer timer.SetTimeout(plcy.Timeouts.UplinkOnly)

		var reader buf.Reader
		if destination.Network == net.Network_TCP {
			reader = buf.NewReader(conn)
		} else {
			reader = NewPacketReader(conn, UDPOverride)
		}
		if err := buf.Copy(reader, output, buf.UpdateActivity(timer)); err != nil {
			return newError("failed to process response").Base(err)
		}

		return nil
	}

	if newCtx != nil {
		ctx = newCtx
	}

	if err := task.Run(ctx, requestDone, task.OnSuccess(responseDone, task.Close(output))); err != nil {
		return newError("connection ends").Base(err)
	}

	return nil
}

func NewPacketReader(conn net.Conn, UDPOverride net.Destination) buf.Reader {
	iConn := conn
	statConn, ok := iConn.(*stat.CounterConnection)
	if ok {
		iConn = statConn.Connection
	}
	var counter stats.Counter
	if statConn != nil {
		counter = statConn.ReadCounter
	}
	if c, ok := iConn.(*internet.PacketConnWrapper); ok && UDPOverride.Address == nil && UDPOverride.Port == 0 {
		return &PacketReader{
			PacketConnWrapper: c,
			Counter:           counter,
		}
	}
	return &buf.PacketReader{Reader: conn}
}

type PacketReader struct {
	*internet.PacketConnWrapper
	stats.Counter
}

func (r *PacketReader) ReadMultiBuffer() (buf.MultiBuffer, error) {
	b := buf.New()
	b.Resize(0, buf.Size)
	n, d, err := r.PacketConnWrapper.ReadFrom(b.Bytes())
	if err != nil {
		b.Release()
		return nil, err
	}
	b.Resize(0, int32(n))
	b.UDP = &net.Destination{
		Address: net.IPAddress(d.(*net.UDPAddr).IP),
		Port:    net.Port(d.(*net.UDPAddr).Port),
		Network: net.Network_UDP,
	}
	if r.Counter != nil {
		r.Counter.Add(int64(n))
	}
	return buf.MultiBuffer{b}, nil
}

func NewPacketWriter(conn net.Conn, h *Handler, ctx context.Context, UDPOverride net.Destination) buf.Writer {
	iConn := conn
	statConn, ok := iConn.(*stat.CounterConnection)
	if ok {
		iConn = statConn.Connection
	}
	var counter stats.Counter
	if statConn != nil {
		counter = statConn.WriteCounter
	}
	if c, ok := iConn.(*internet.PacketConnWrapper); ok {
		return &PacketWriter{
			PacketConnWrapper: c,
			Counter:           counter,
			Handler:           h,
			Context:           ctx,
			UDPOverride:       UDPOverride,
		}
	}
	return &buf.SequentialWriter{Writer: conn}
}

type PacketWriter struct {
	*internet.PacketConnWrapper
	stats.Counter
	*Handler
	context.Context
	UDPOverride net.Destination
}

func (w *PacketWriter) WriteMultiBuffer(mb buf.MultiBuffer) error {
	for {
		mb2, b := buf.SplitFirst(mb)
		mb = mb2
		if b == nil {
			break
		}
		var n int
		var err error
		if b.UDP != nil {
			if w.UDPOverride.Address != nil {
				b.UDP.Address = w.UDPOverride.Address
			}
			if w.UDPOverride.Port != 0 {
				b.UDP.Port = w.UDPOverride.Port
			}
			if w.Handler.config.useIP() && b.UDP.Address.Family().IsDomain() {
				ip := w.Handler.resolveIP(w.Context, b.UDP.Address.Domain(), nil)
				if ip != nil {
					b.UDP.Address = ip
				}
			}
			destAddr, _ := net.ResolveUDPAddr("udp", b.UDP.NetAddr())
			if destAddr == nil {
				b.Release()
				continue
			}
			n, err = w.PacketConnWrapper.WriteTo(b.Bytes(), destAddr)
		} else {
			n, err = w.PacketConnWrapper.Write(b.Bytes())
		}
		b.Release()
		if err != nil {
			buf.ReleaseMulti(mb)
			return err
		}
		if w.Counter != nil {
			w.Counter.Add(int64(n))
		}
	}
	return nil
}

type FragmentWriter struct {
	io.Writer
	minLength   int
	maxLength   int
	minInterval time.Duration
	maxInterval time.Duration
	startPacket int
	endPacket   int
	PacketCount int
}

func (w *FragmentWriter) Write(buf []byte) (int, error) {
	w.PacketCount += 1
	if (w.startPacket != 0 && (w.PacketCount < w.startPacket || w.PacketCount > w.endPacket)) || len(buf) <= w.minLength {
		return w.Writer.Write(buf)
	}

	nTotal := 0
	for {
		randomBytesTo := int(randBetween(int64(w.minLength), int64(w.maxLength))) + nTotal
		if randomBytesTo > len(buf) {
			randomBytesTo = len(buf)
		}
		n, err := w.Writer.Write(buf[nTotal:randomBytesTo])
		if err != nil {
			return nTotal + n, err
		}
		nTotal += n

		if nTotal >= len(buf) {
			return nTotal, nil
		}

		randomInterval := randBetween(int64(w.minInterval), int64(w.maxInterval))
		time.Sleep(time.Duration(randomInterval))
	}
}

// stolen from github.com/xtls/xray-core/transport/internet/reality
func randBetween(left int64, right int64) int64 {
	if left == right {
		return left
	}
	bigInt, _ := rand.Int(rand.Reader, big.NewInt(right-left))
	return left + bigInt.Int64()
}

type FragmentedClientHelloConn struct {
	net.Conn
	PacketCount int
	minLength   int
	maxLength   int
	minInterval time.Duration
	maxInterval time.Duration
}

func (c *FragmentedClientHelloConn) Write(b []byte) (n int, err error) {
	if len(b) >= 5 && b[0] == 22 && c.PacketCount == 0 {
		n, err = sendFragmentedClientHello(c, b, c.minLength, c.maxLength)

		if err == nil {
			c.PacketCount++
			return n, err
		}
	}

	return c.Conn.Write(b)
}

func sendFragmentedClientHello(conn *FragmentedClientHelloConn, clientHello []byte, minFragmentSize, maxFragmentSize int) (n int, err error) {
	if len(clientHello) < 5 || clientHello[0] != 22 {
		return 0, errors.New("not a valid TLS ClientHello message")
	}

	clientHelloLen := (int(clientHello[3]) << 8) | int(clientHello[4])

	clientHelloData := clientHello[5:]
	for i := 0; i < clientHelloLen; {
		fragmentEnd := i + int(randBetween(int64(minFragmentSize), int64(maxFragmentSize)))
		if fragmentEnd > clientHelloLen {
			fragmentEnd = clientHelloLen
		}

		fragment := clientHelloData[i:fragmentEnd]
		i = fragmentEnd

		err = writeFragmentedRecord(conn, 22, fragment, clientHello)
		if err != nil {
			return 0, err
		}
	}

	return len(clientHello), nil
}

func writeFragmentedRecord(c *FragmentedClientHelloConn, contentType uint8, data []byte, clientHello []byte) error {
	header := make([]byte, 5)
	header[0] = byte(clientHello[0])

	tlsVersion := (int(clientHello[1]) << 8) | int(clientHello[2])
	binary.BigEndian.PutUint16(header[1:], uint16(tlsVersion))

	binary.BigEndian.PutUint16(header[3:], uint16(len(data)))
	_, err := c.Conn.Write(append(header, data...))
	randomInterval := randBetween(int64(c.minInterval), int64(c.maxInterval))
	time.Sleep(time.Duration(randomInterval))

	return err
}
