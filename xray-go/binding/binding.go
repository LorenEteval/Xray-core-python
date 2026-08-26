// Package binding contains the Go-facing implementation used by the Python
// extension. Keeping it separate lets xray-go remain an exact upstream tree
// apart from the explicitly owned binding files.
package binding

import (
	"context"
	"strings"
	"time"

	statsservice "github.com/xtls/xray-core/app/stats/command"
	creflect "github.com/xtls/xray-core/common/reflect"
	"github.com/xtls/xray-core/core"
	"github.com/xtls/xray-core/infra/conf/serial"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
)

// NewServerFromJSON builds an Xray server from an in-memory JSON document.
func NewServerFromJSON(jsonString string) (core.Server, error) {
	config, err := serial.DecodeJSONConfig(strings.NewReader(jsonString))
	if err != nil {
		return nil, err
	}

	builtConfig, err := config.Build()
	if err != nil {
		return nil, err
	}

	return core.New(builtConfig)
}

// QueryStats queries an Xray API server and returns the JSON response used by
// the Python API. The error strings preserve the binding's historical API.
func QueryStats(serverAddr string, timeout int, pattern string, reset bool) string {
	ctx, cancel := context.WithTimeout(
		context.Background(),
		time.Duration(timeout)*time.Second,
	)
	defer cancel()

	conn, err := grpc.DialContext(
		ctx,
		serverAddr,
		grpc.WithTransportCredentials(insecure.NewCredentials()),
		grpc.WithBlock(),
	)
	if err != nil {
		return "Failed to dial API server"
	}
	defer conn.Close()

	client := statsservice.NewStatsServiceClient(conn)
	response, err := client.QueryStats(ctx, &statsservice.QueryStatsRequest{
		Pattern: pattern,
		Reset_:  reset,
	})
	if err != nil {
		return "Failed to query stats"
	}
	if response == nil {
		return "Failed to get proto"
	}
	if result, ok := creflect.MarshalToJson(response, true); ok {
		return result
	}
	return "Failed to encode proto"
}
