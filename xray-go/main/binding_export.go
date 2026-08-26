package main

/*
#include <stdlib.h>
*/
import "C"

import (
	"os"
	"os/signal"
	"runtime"
	"runtime/debug"
	"syscall"
	"unsafe"

	"github.com/xtls/xray-core/binding"
)

//export freeCString
func freeCString(ptr *C.char) {
	C.free(unsafe.Pointer(ptr))
}

//export queryStats
func queryStats(serverAddr string, timeout int, pattern string, reset bool) *C.char {
	return C.CString(binding.QueryStats(serverAddr, timeout, pattern, reset))
}

//export startFromJSON
func startFromJSON(jsonString string) {
	server, err := binding.NewServerFromJSON(jsonString)
	if err != nil {
		os.Exit(23)
	}

	if err := server.Start(); err != nil {
		os.Exit(-1)
	}
	defer server.Close()

	runtime.GC()
	debug.FreeOSMemory()

	osSignals := make(chan os.Signal, 1)
	signal.Notify(osSignals, os.Interrupt, syscall.SIGTERM)
	<-osSignals
}
