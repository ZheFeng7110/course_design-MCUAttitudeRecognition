# TFLite for Microcontrollers 静态库（Cortex-M7 / STM32H723）
# 计划 Phase 7.2。第三方依赖以 git submodule 集成于 deps/（勿在 submodule 内写文件）。
# CMSIS Core 头直接用 CubeMX 工程自带 OfflineDevice/Drivers/CMSIS/Include。
#
# 源收集采用"白名单目录 + 文件名子串跳过"的方式（string(FIND)，不用正则）：
#  - 只从明确列出的目录收集 .cc；
#  - 跳过测试/示例/平台专用文件。
# 若上游目录结构变化导致链接缺符号，先在这里补对应目录/跳过项。

set(TFLM_DIR ${CMAKE_SOURCE_DIR}/../deps/tflite-micro)
set(TFLM_CMSIS_NN_DIR ${CMAKE_SOURCE_DIR}/../deps/CMSIS-NN)

option(ATTITUDE_ENABLE_CMSIS_NN "Use CMSIS-NN optimized int8 kernels" ON)

# ---- 通用收集函数 -----------------------------------------------------------
# tflm_collect_sources(<out> <dir> [RECURSE] [EXT cc|c] [SKIP_NAME <子串>...])
# 收集 <dir> 下指定扩展名（默认 cc）的源文件；文件名含 _test. / _testlib. /
# _annotate. 的跳过，另可经 SKIP_NAME 追加文件名子串跳过项。
function(tflm_collect_sources out dir)
    set(ext "cc")
    set(skip_names "")
    set(recurse FALSE)
    set(_mode none)
    foreach(arg IN LISTS ARGN)
        if(arg STREQUAL "RECURSE")
            set(recurse TRUE)
            set(_mode none)
        elseif(arg STREQUAL "EXT")
            set(_mode ext)
        elseif(arg STREQUAL "SKIP_NAME")
            set(_mode skip)
        elseif(_mode STREQUAL "ext")
            set(ext ${arg})
            set(_mode none)
        elseif(_mode STREQUAL "skip")
            list(APPEND skip_names ${arg})
        endif()
    endforeach()
    if(recurse)
        file(GLOB_RECURSE found ${dir}/*.${ext})
    else()
        file(GLOB found ${dir}/*.${ext})
    endif()

    set(collected "")
    foreach(f IN LISTS found)
        get_filename_component(name ${f} NAME)
        set(skip FALSE)
        foreach(bad IN ITEMS "_test." "_testlib." "_annotate." ${skip_names})
            string(FIND ${name} ${bad} pos)
            if(NOT pos EQUAL -1)
                set(skip TRUE)
                break()
            endif()
        endforeach()
        if(NOT skip)
            list(APPEND collected ${f})
        endif()
    endforeach()
    set(${out} ${collected} PARENT_SCOPE)
endfunction()

# ---- TFLM 源收集 -------------------------------------------------------------
# tensorflow/lite 与 mlir/lite 下的目录结构干净，直接递归收集。
set(TFLM_CC_SOURCES "")
foreach(dir IN ITEMS
        ${TFLM_DIR}/tensorflow/lite/c
        ${TFLM_DIR}/tensorflow/lite/core
        ${TFLM_DIR}/tensorflow/lite/kernels
        ${TFLM_DIR}/tensorflow/lite/schema
        # ErrorReporter::Report / GetBuiltinCode 实现被上游移到了 mlir/lite 下的镜像路径
        ${TFLM_DIR}/tensorflow/compiler/mlir/lite/core/api
        ${TFLM_DIR}/tensorflow/compiler/mlir/lite/schema)
    tflm_collect_sources(dir_sources ${dir} RECURSE)
    list(APPEND TFLM_CC_SOURCES ${dir_sources})
endforeach()

# micro 树混有大量平台移植/测试目录，只递归收集白名单子目录。
# cortex_m_generic 仅取 debug_log.cc；micro_time.cc 依赖平台计时实现，显式排除。
set(TFLM_MICRO_SUBDIRS
    arena_allocator
    compression
    memory_planner
    tflite_bridge
    cortex_m_generic
)
tflm_collect_sources(micro_top ${TFLM_DIR}/tensorflow/lite/micro)
list(APPEND TFLM_CC_SOURCES ${micro_top})
foreach(sub IN LISTS TFLM_MICRO_SUBDIRS)
    tflm_collect_sources(sub_sources ${TFLM_DIR}/tensorflow/lite/micro/${sub} RECURSE)
    list(APPEND TFLM_CC_SOURCES ${sub_sources})
endforeach()
list(REMOVE_ITEM TFLM_CC_SOURCES
    ${TFLM_DIR}/tensorflow/lite/micro/cortex_m_generic/micro_time.cc)

# 默认参考内核：只取 kernels/ 顶层，不进 cmsis_nn / xtensa / ethos_u 等子目录。
tflm_collect_sources(kernel_sources ${TFLM_DIR}/tensorflow/lite/micro/kernels)
list(APPEND TFLM_CC_SOURCES ${kernel_sources})

set(TFLM_INCLUDES
    ${TFLM_DIR}
    ${CMAKE_SOURCE_DIR}/../deps/flatbuffers/include
    ${CMAKE_SOURCE_DIR}/../deps/gemmlowp
    ${CMAKE_SOURCE_DIR}/../deps/ruy
    ${CMAKE_SOURCE_DIR}/Drivers/CMSIS/Include
    ${CMAKE_SOURCE_DIR}/Drivers/CMSIS/Device/ST/STM32H7xx/Include
)

set(TFLM_EXTRA_SOURCES "")
set(TFLM_EXTRA_INCLUDES "")
set(TFLM_EXTRA_DEFS "")

if (ATTITUDE_ENABLE_CMSIS_NN)
    if (NOT EXISTS ${TFLM_CMSIS_NN_DIR}/Include/arm_nnfunctions.h)
        message(WARNING "[tflm] CMSIS-NN 未找到（deps/CMSIS-NN），回退默认参考内核")
    else ()
        file(GLOB CMSIS_NN_KERNEL_SRCS ${TFLM_DIR}/tensorflow/lite/micro/kernels/cmsis_nn/*.cc)
        # CMSIS-NN 内核与默认内核重复注册同名 op：
        # 按文件名移除 kernels/ 顶层同名默认实现（精确路径匹配，无正则）。
        foreach(f IN LISTS CMSIS_NN_KERNEL_SRCS)
            get_filename_component(name ${f} NAME)
            list(REMOVE_ITEM TFLM_CC_SOURCES
                ${TFLM_DIR}/tensorflow/lite/micro/kernels/${name})
        endforeach()

        # F16/F32 变体不参与（与上游 cmsis_nn.inc 的 ARM_NN_ENABLE_F16/F32=0 一致）
        tflm_collect_sources(CMSIS_NN_LIB_SRCS ${TFLM_CMSIS_NN_DIR}/Source RECURSE EXT c
            SKIP_NAME "_f16." "_f32." "arm_nntables_flt.")

        list(APPEND TFLM_EXTRA_SOURCES ${CMSIS_NN_KERNEL_SRCS} ${CMSIS_NN_LIB_SRCS})
        list(APPEND TFLM_EXTRA_INCLUDES
            ${TFLM_CMSIS_NN_DIR}
            ${TFLM_CMSIS_NN_DIR}/Include
        )
        list(APPEND TFLM_EXTRA_DEFS CMSIS_NN)
    endif ()
endif ()

add_library(tflm STATIC ${TFLM_CC_SOURCES} ${TFLM_EXTRA_SOURCES})
# 纯 C++ 编译：关闭模块扫描，规避 GCC15 对 flatbuffers 头的 TU-local 诊断
set_target_properties(tflm PROPERTIES CXX_SCAN_FOR_MODULES OFF)
target_include_directories(tflm PUBLIC ${TFLM_INCLUDES} ${TFLM_EXTRA_INCLUDES})
target_compile_definitions(tflm PUBLIC ${TFLM_EXTRA_DEFS})
# cortex_m_generic/micro_time.cc 经 CMSIS_DEVICE 宏包含设备 CMSIS 头访问 DWT；
# stm32h7xx.h 需要器件宏选择具体型号。
target_compile_definitions(tflm PRIVATE
    CMSIS_DEVICE_ARM_CORTEX_M_XX_HEADER_FILE="stm32h7xx.h"
    STM32H723xx
)
target_compile_options(tflm PRIVATE
    $<$<CONFIG:Debug>:-O2>
    $<$<CONFIG:Release>:-O3>
    $<$<COMPILE_LANGUAGE:CXX>:-fno-rtti>
    $<$<COMPILE_LANGUAGE:CXX>:-fno-exceptions>
)
