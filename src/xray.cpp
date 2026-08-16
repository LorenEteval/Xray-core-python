#include <string>
#if defined(__MINGW32__) && defined(_M_ARM64)
    // CPython 3.14t uses MSVC's __getReg(18) intrinsic to read the Windows
    // ARM64 thread environment block, but LLVM-MinGW does not provide it.
    // Windows reserves x18 for that pointer, so provide the equivalent here.
    #include <cstdint>
    static inline std::uintptr_t getArm64ThreadPointer()
    {
        std::uintptr_t value;
        __asm__ __volatile__("mov %0, x18" : "=r"(value));
        return value;
    }
    #define __getReg(registerNumber) getArm64ThreadPointer()
#endif
#if defined _WIN64
    #define _hypot hypot
    #include <cmath>
#endif
#include <pybind11/pybind11.h>
#if defined(__MINGW32__) && defined(_M_ARM64)
    #undef __getReg
#endif

#include "xray.h"

namespace py = pybind11;

namespace {
    std::string queryStats(const std::string& apiServer, int timeout, const std::string& myPattern, bool reset)
    {
        GoString apiServerString{apiServer.data(), static_cast<ptrdiff_t>(apiServer.size())};
        GoString myPatternString{myPattern.data(), static_cast<ptrdiff_t>(myPattern.size())};

        char* ptr = nullptr;

        {
            py::gil_scoped_release release;

            ptr = queryStats(apiServerString, static_cast<GoInt>(timeout), myPatternString, static_cast<GoUint8>(reset));

            py::gil_scoped_acquire acquire;
        }

        if (ptr == nullptr) {
            return "";
        }
        else {
            std::string result{ptr};

            freeCString(ptr);

            return result;
        }
    }

    void startFromJSON(const std::string& json)
    {
        GoString jsonString{json.data(), static_cast<ptrdiff_t>(json.size())};

        {
            py::gil_scoped_release release;

            startFromJSON(jsonString);

            py::gil_scoped_acquire acquire;
        }
    }

    // TODO: After auditing and testing the C++ and Go paths for free-threaded
    // safety, use PYBIND11_MODULE(xray, m, py::mod_gil_not_used()) so importing
    // this extension does not cause free-threaded CPython to enable the GIL.
    PYBIND11_MODULE(xray, m) {
        m.def("queryStats",
            &queryStats,
            "Query statistics from Xray",
            py::arg("apiServer"), py::arg("timeout"), py::arg("myPattern"), py::arg("reset"));

        m.def("startFromJSON",
            &startFromJSON,
            "Start Xray client with JSON string",
            py::arg("json"));

        m.attr("__version__") = "1.8.26.8";
    }
}
