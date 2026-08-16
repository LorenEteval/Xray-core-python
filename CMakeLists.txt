cmake_minimum_required(VERSION 3.15)
project(xray C CXX)

set(CMAKE_C_STANDARD 99)
set(CMAKE_CXX_STANDARD 11)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
set(PYBIND11_FINDPYTHON ON)
if (PYBIND11_SOURCE_DIR)
    add_subdirectory("${PYBIND11_SOURCE_DIR}" pybind11)
else()
    find_package(pybind11 CONFIG REQUIRED)
endif ()

if (NOT XRAY_CORE_ARCHIVE)
    set(XRAY_CORE_ARCHIVE "${CMAKE_SOURCE_DIR}/gobuild/xray.a")
    if (WIN32)
        set(XRAY_CORE_ARCHIVE "${CMAKE_SOURCE_DIR}/gobuild/xray.lib")
    endif ()
endif ()

if (NOT XRAY_CORE_INCLUDE_DIR)
    set(XRAY_CORE_INCLUDE_DIR "${CMAKE_SOURCE_DIR}/gobuild")
endif ()

pybind11_add_module(${PROJECT_NAME} src/xray.cpp)

if (WIN32)
    if (MINGW)
        target_compile_options(${PROJECT_NAME} PRIVATE "-Wa,-mbig-obj")
        target_link_options(
            ${PROJECT_NAME} PRIVATE
            "-static-libgcc" "-static-libstdc++"
            "-Wl,-Bstatic,--whole-archive"
            "-lwinpthread"
            "-Wl,--no-whole-archive"
        )
    endif ()

    target_link_libraries(
        ${PROJECT_NAME} PRIVATE
        "${XRAY_CORE_ARCHIVE}"
    )
else()
    target_link_libraries(
        ${PROJECT_NAME} PRIVATE
        "${XRAY_CORE_ARCHIVE}"
        "-lresolv"
    )

    if (APPLE)
        target_link_libraries(
            ${PROJECT_NAME} PRIVATE
            "-framework CoreFoundation"
            "-framework Security"
        )
    endif ()
endif ()

target_include_directories(${PROJECT_NAME} PRIVATE "${XRAY_CORE_INCLUDE_DIR}")
