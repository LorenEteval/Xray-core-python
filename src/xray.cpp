#include <string>
#if defined _WIN64
    #define _hypot hypot
    #include <cmath>
#endif
#include <pybind11/pybind11.h>

#include "xray.h"

namespace py = pybind11;

namespace {
    std::string queryStats(const std::string& apiServer, int timeout, const std::string& myPattern, bool reset)
    {
        GoString apiServerString{apiServer.data(), static_cast<ptrdiff_t>(apiServer.size())};
        GoString myPatternString{myPattern.data(), static_cast<ptrdiff_t>(myPattern.size())};

        char* ptr = queryStats(apiServerString, static_cast<GoInt>(timeout), myPatternString, static_cast<GoUint8>(reset));

        std::string result{ptr};

        freeCString(ptr);

        return result;
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

    PYBIND11_MODULE(xray, m) {
        m.def("queryStats",
            &queryStats,
            "Query statistics from Xray",
            py::arg("apiServer"), py::arg("timeout"), py::arg("myPattern"), py::arg("reset"));

        m.def("startFromJSON",
            &startFromJSON,
            "Start Xray client with JSON string",
            py::arg("json"));

        m.attr("__version__") = "1.8.24.11";
    }
}
