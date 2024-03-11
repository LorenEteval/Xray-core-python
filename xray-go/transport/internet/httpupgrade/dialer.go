package httpupgrade

import (
	"bufio"
	"context"
	"net/http"
	"net/url"
	"strings"

	"github.com/xtls/xray-core/common"
	"github.com/xtls/xray-core/common/net"
	"github.com/xtls/xray-core/common/session"
	"github.com/xtls/xray-core/transport/internet"
	"github.com/xtls/xray-core/transport/internet/stat"
	"github.com/xtls/xray-core/transport/internet/tls"
)

func dialhttpUpgrade(ctx context.Context, dest net.Destination, streamSettings *internet.MemoryStreamConfig) (net.Conn, error) {
	transportConfiguration := streamSettings.ProtocolSettings.(*Config)

	pconn, err := internet.DialSystem(ctx, dest, streamSettings.SocketSettings)
	if err != nil {
		newError("failed to dial to ", dest).Base(err).AtError().WriteToLog()
		return nil, err
	}

	var conn net.Conn
	var requestURL url.URL
	if config := tls.ConfigFromStreamSettings(streamSettings); config != nil {
		tlsConfig := config.GetTLSConfig(tls.WithDestination(dest), tls.WithNextProto("http/1.1"))
		if fingerprint := tls.GetFingerprint(config.Fingerprint); fingerprint != nil {
			conn = tls.UClient(pconn, tlsConfig, fingerprint)
			if err := conn.(*tls.UConn).WebsocketHandshakeContext(ctx); err != nil {
				return nil, err
			}
		} else {
			conn = tls.Client(pconn, tlsConfig)
		}

		requestURL.Scheme = "https"
	} else {
		requestURL.Scheme = "http"
	}

	requestURL.Host = dest.NetAddr()
	requestURL.Path = transportConfiguration.GetNormalizedPath()
	req := &http.Request{
		Method: http.MethodGet,
		URL:    &requestURL,
		Host:   transportConfiguration.Host,
		Header: make(http.Header),
	}
	req.Header.Set("Connection", "upgrade")
	req.Header.Set("Upgrade", "websocket")

	err = req.Write(conn)
	if err != nil {
		return nil, err
	}

	// TODO The bufio usage here is unreliable
	resp, err := http.ReadResponse(bufio.NewReader(conn), req) // nolint:bodyclose
	if err != nil {
		return nil, err
	}

	if resp.Status == "101 Switching Protocols" &&
		strings.ToLower(resp.Header.Get("Upgrade")) == "websocket" &&
		strings.ToLower(resp.Header.Get("Connection")) == "upgrade" {
		return conn, nil
	}
	return nil, newError("unrecognized reply")
}

func dial(ctx context.Context, dest net.Destination, streamSettings *internet.MemoryStreamConfig) (stat.Connection, error) {
	newError("creating connection to ", dest).WriteToLog(session.ExportIDToError(ctx))

	conn, err := dialhttpUpgrade(ctx, dest, streamSettings)
	if err != nil {
		return nil, newError("failed to dial request to ", dest).Base(err)
	}
	return stat.Connection(conn), nil
}

func init() {
	common.Must(internet.RegisterTransportDialer(protocolName, dial))
}
