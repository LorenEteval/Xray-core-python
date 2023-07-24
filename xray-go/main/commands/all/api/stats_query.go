package api

import (
	statsService "github.com/xtls/xray-core/app/stats/command"
	"github.com/xtls/xray-core/main/commands/base"
)

var cmdQueryStats = &base.Command{
	CustomFlags: true,
	UsageLine:   "{{.Exec}} api statsquery [--server=127.0.0.1:8080] [-pattern '']",
	Short:       "Query statistics",
	Long: `
Query statistics from Xray.
Arguments:
	-s, -server 
		The API server address. Default 127.0.0.1:8080
	-t, -timeout
		Timeout seconds to call API. Default 3
	-pattern
		Pattern of the query.
	-reset
		Reset the counter to fetching its value.
Example:
	{{.Exec}} {{.LongName}} --server=127.0.0.1:8080 -pattern "counter_"
`,
	Run: executeQueryStats,
}

func QueryStats(serverAddr string, timeout int, pattern string, reset bool) string {
	conn, ctx, close := dialAPIServerTarget(serverAddr, timeout)

	if conn == nil {
		// Failed to dial API server
		return "Failed to dial API server"
	}
	defer close()

	client := statsService.NewStatsServiceClient(conn)
	r := &statsService.QueryStatsRequest{
		Pattern: pattern,
		Reset_:  reset,
	}
	resp, err := client.QueryStats(ctx, r)
	if err != nil {
		// Failed to query stats
		return "Failed to query stats"
	}
	return getJSONResponse(resp)
}

func executeQueryStats(cmd *base.Command, args []string) {
	setSharedFlags(cmd)
	pattern := cmd.Flag.String("pattern", "", "")
	reset := cmd.Flag.Bool("reset", false, "")
	cmd.Flag.Parse(args)

	conn, ctx, close := dialAPIServer()
	defer close()

	client := statsService.NewStatsServiceClient(conn)
	r := &statsService.QueryStatsRequest{
		Pattern: *pattern,
		Reset_:  *reset,
	}
	resp, err := client.QueryStats(ctx, r)
	if err != nil {
		base.Fatalf("failed to query stats: %s", err)
	}
	showJSONResponse(resp)
}
