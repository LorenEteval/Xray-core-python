cmake_minimum_required(VERSION 3.12)
project(xray C CXX)

set(CMAKE_C_STANDARD 99)
set(CMAKE_CXX_STANDARD 11)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
set(CMAKE_LIBRARY_OUTPUT_DIRECTORY ${CMAKE_SOURCE_DIR}/build/lib/${PROJECT_NAME})

add_subdirectory(pybind11)

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
        ${CMAKE_SOURCE_DIR}/gobuild/xray.lib
    )
else()
    target_link_libraries(
        ${PROJECT_NAME} PRIVATE
        ${CMAKE_SOURCE_DIR}/gobuild/xray.a
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

target_include_directories(${PROJECT_NAME} PRIVATE gobuild)
