package api

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"reflect"
	"strings"
	"time"

	"github.com/xtls/xray-core/common/buf"
	"github.com/xtls/xray-core/main/commands/base"
	"google.golang.org/grpc"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"
)

type serviceHandler func(ctx context.Context, conn *grpc.ClientConn, cmd *base.Command, args []string) string

var (
	apiServerAddrPtr string
	apiTimeout       int
)

func setSharedFlags(cmd *base.Command) {
	cmd.Flag.StringVar(&apiServerAddrPtr, "s", "127.0.0.1:8080", "")
	cmd.Flag.StringVar(&apiServerAddrPtr, "server", "127.0.0.1:8080", "")
	cmd.Flag.IntVar(&apiTimeout, "t", 3, "")
	cmd.Flag.IntVar(&apiTimeout, "timeout", 3, "")
}

func dialAPIServerTarget(serverAddr string, timeout int) (conn *grpc.ClientConn, ctx context.Context, close func()) {
	ctx, cancel := context.WithTimeout(context.Background(), time.Duration(timeout)*time.Second)
	conn, err := grpc.DialContext(ctx, serverAddr, grpc.WithInsecure(), grpc.WithBlock())
	if err != nil {
		cancel()
		return nil, nil, nil
	}
	close = func() {
		cancel()
		conn.Close()
	}
	return
}

func dialAPIServer() (conn *grpc.ClientConn, ctx context.Context, close func()) {
	ctx, cancel := context.WithTimeout(context.Background(), time.Duration(apiTimeout)*time.Second)
	conn, err := grpc.DialContext(ctx, apiServerAddrPtr, grpc.WithInsecure(), grpc.WithBlock())
	if err != nil {
		base.Fatalf("failed to dial %s", apiServerAddrPtr)
	}
	close = func() {
		cancel()
		conn.Close()
	}
	return
}

// loadArg loads one arg, maybe an remote url, or local file path
func loadArg(arg string) (out io.Reader, err error) {
	var data []byte
	switch {
	case strings.HasPrefix(arg, "http://"), strings.HasPrefix(arg, "https://"):
		data, err = fetchHTTPContent(arg)

	case arg == "stdin:":
		data, err = io.ReadAll(os.Stdin)

	default:
		data, err = os.ReadFile(arg)
	}

	if err != nil {
		return
	}
	out = bytes.NewBuffer(data)
	return
}

// fetchHTTPContent dials https for remote content
func fetchHTTPContent(target string) ([]byte, error) {
	parsedTarget, err := url.Parse(target)
	if err != nil {
		return nil, err
	}

	if s := strings.ToLower(parsedTarget.Scheme); s != "http" && s != "https" {
		return nil, fmt.Errorf("invalid scheme: %s", parsedTarget.Scheme)
	}

	client := &http.Client{
		Timeout: 30 * time.Second,
	}
	resp, err := client.Do(&http.Request{
		Method: "GET",
		URL:    parsedTarget,
		Close:  true,
	})
	if err != nil {
		return nil, fmt.Errorf("failed to dial to %s", target)
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("unexpected HTTP status code: %d", resp.StatusCode)
	}

	content, err := buf.ReadAllToBytes(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read HTTP response")
	}

	return content, nil
}

func protoToJSONString(m proto.Message, _, indent string) (string, error) {
	ops := protojson.MarshalOptions{
		Indent:          indent,
		EmitUnpopulated: true,
	}
	b, err := ops.Marshal(m)
	return string(b), err
}

func getJSONResponse(m proto.Message) string {
	if isNil(m) {
		return "Failed to get proto"
	}
	output, err := protoToJSONString(m, "", "    ")
	if err != nil {
		return "Failed to encode proto"
	}
	return output
}

func showJSONResponse(m proto.Message) {
	if isNil(m) {
		return
	}
	output, err := protoToJSONString(m, "", "    ")
	if err != nil {
		fmt.Fprintf(os.Stdout, "%v\n", m)
		base.Fatalf("error encode json: %s", err)
	}
	fmt.Println(output)
}

func isNil(i interface{}) bool {
	vi := reflect.ValueOf(i)
	if vi.Kind() == reflect.Ptr {
		return vi.IsNil()
	}
	return i == nil
}
