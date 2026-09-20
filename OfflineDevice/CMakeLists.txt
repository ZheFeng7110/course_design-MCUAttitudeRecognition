cmake_minimum_required(VERSION 3.30...4.4.0)

#
# This file is generated only once,
# and is not re-generated if converter is called multiple times.
#
# User is free to modify the file as much as necessary
#

option(DO_NOT_USE_CCACHE "Disable CCache, even if it is available" OFF)

find_program(CCACHE_PROGRAM ccache)
if (CCACHE_PROGRAM AND (NOT DO_NOT_USE_CCACHE))
    message(STATUS "CCache found: ${CCACHE_PROGRAM}")
    set(CMAKE_C_COMPILER_LAUNCHER ${CCACHE_PROGRAM})
    set(CMAKE_CXX_COMPILER_LAUNCHER ${CCACHE_PROGRAM})
else ()
    message(STATUS "CCache not found or disabled (DO_NOT_USE_CCACHE=${DO_NOT_USE_CCACHE}).")
endif ()

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS ON)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_SCAN_FOR_MODULES ON)

if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE "Debug")
endif()

set(CMAKE_PROJECT_NAME OfflineDevice)

set(CMAKE_EXPORT_COMPILE_COMMANDS TRUE)

project(${CMAKE_PROJECT_NAME} C CXX ASM)
message("Build type: " ${CMAKE_BUILD_TYPE})

enable_language(C CXX ASM)

option(ATTITUDE_ENABLE_TFLM "Enable TFLM if model_data exists" OFF)

add_executable(${CMAKE_PROJECT_NAME})

add_subdirectory(cmake/stm32cubemx)
include(cmake/emdevif_config.cmake)

# Remove wrong libob.a library dependency when using cpp files
list(REMOVE_ITEM CMAKE_C_IMPLICIT_LINK_LIBRARIES ob)

include(${CMAKE_CURRENT_LIST_DIR}/cmake/get_cpm.cmake)
CPMAddPackage(
    NAME printf
    GITHUB_REPOSITORY mpaland/printf
    GIT_TAG v4.0.0
    VERSION 4.0.0
    DOWNLOAD_ONLY
)
if (printf_ADDED)
    add_library(printf STATIC)
    target_sources(printf
        PRIVATE ${printf_SOURCE_DIR}/printf.c

        PUBLIC FILE_SET header TYPE HEADERS BASE_DIRS ${printf_SOURCE_DIR}
            FILES ${printf_SOURCE_DIR}/printf.h
    )
else ()
    message(FATAL_ERROR "[${PROJECT_NAME}]: CPM: Failed to add package `printf`")
endif ()

target_link_libraries(${CMAKE_PROJECT_NAME}
    stm32cubemx
    emdevif
    emdevif_stm32_peripheral
    printf
)

# 应用代码：C++23 模块单元（.cppm）
file(GLOB ATTITUDE_APP_MODULES
    "${CMAKE_CURRENT_SOURCE_DIR}/App/modules/*.cppm"
)
target_sources(${CMAKE_PROJECT_NAME} PRIVATE
    FILE_SET attitude_modules TYPE CXX_MODULES FILES ${ATTITUDE_APP_MODULES}
)

# 应用代码：链接期注入普通 TU（.cpp）
file(GLOB ATTITUDE_APP_PLAIN_SOURCES
    "${CMAKE_CURRENT_SOURCE_DIR}/App/src/*.cpp"
)
target_sources(${CMAKE_PROJECT_NAME} PRIVATE ${ATTITUDE_APP_PLAIN_SOURCES})

target_include_directories(${CMAKE_PROJECT_NAME} PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/App/inc
)

target_compile_options(${CMAKE_PROJECT_NAME} PRIVATE -Wall -Wextra -Wpedantic)

# ---- TFLM 推理路径（Phase 7）：模型生成后开启 ----
# 1. model/tools/gen_c_array.py 生成 App/src/model_data.cc
if (ATTITUDE_ENABLE_TFLM)
    include(cmake/tflm.cmake)
    if (EXISTS ${CMAKE_CURRENT_SOURCE_DIR}/App/inc/model_data.h
        AND EXISTS ${CMAKE_CURRENT_SOURCE_DIR}/App/src/model_data.cc)
        target_sources(${CMAKE_PROJECT_NAME}
            PRIVATE FILE_SET attitude_modules TYPE CXX_MODULES FILES
                ${CMAKE_CURRENT_SOURCE_DIR}/App/modules/tflite/attitude.tflite.cppm

            PRIVATE
                ${CMAKE_CURRENT_SOURCE_DIR}/App/src/model_data.cc
                ${CMAKE_CURRENT_SOURCE_DIR}/App/src/tflite/tflite_backend.cpp
        )
        target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE ATTITUDE_ENABLE_TFLM)
        target_link_libraries(${CMAKE_PROJECT_NAME} tflm)
    else ()
        message(WARNING
            "[ATTITUDE_ENABLE_TFLM] 缺少 App/src/model_data.{h,cc}：先训练导出并运行 "
            "model/tools/gen_c_array.py 后重新配置；本次仅编译 tflm 静态库")
    endif ()
endif ()
