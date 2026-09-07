# TFLite for Microcontrollers 静态库（Cortex-M7 / STM32H723）
# 计划 Phase 7.2。第三方依赖以 git submodule 集成于 deps/（勿在 submodule 内写文件）。
# CMSIS Core 头直接用 CubeMX 工程自带 OfflineDevice/Drivers/CMSIS/Include。
#
# 源收集若与实际构建冲突（计划 Assumption #4），退回显式源列表：
# 底本可用 tflite-micro 仓库 Makefile 的 MICROLITE_CC_SRCS。

set(TFLM_DIR ${CMAKE_SOURCE_DIR}/../deps/tflite-micro)
set(TFLM_CMSIS_NN_DIR ${CMAKE_SOURCE_DIR}/../deps/CMSIS-NN)

option(ATTITUDE_ENABLE_CMSIS_NN "Use CMSIS-NN optimized int8 kernels" ON)

file(GLOB_RECURSE TFLM_CC_SOURCES CONFIGURE_DEPENDS
    ${TFLM_DIR}/tensorflow/lite/c/*.cc
    ${TFLM_DIR}/tensorflow/lite/core/*.cc
    ${TFLM_DIR}/tensorflow/lite/kernels/*.cc
    ${TFLM_DIR}/tensorflow/lite/micro/*.cc
    ${TFLM_DIR}/tensorflow/lite/schema/*.cc
    # ErrorReporter::Report / GetBuiltinCode 实现被上游移到了 mlir/lite 下的镜像路径
    ${TFLM_DIR}/tensorflow/compiler/mlir/lite/core/api/*.cc
    ${TFLM_DIR}/tensorflow/compiler/mlir/lite/schema/*.cc
)
# 排除：测试 / 平台专用（arc、bluepill、chre、ceva、hexagon、xtensa、corstone、riscv32、msp430）
# 以及 ethos_u / python 目录；仅保留通用 Cortex-M 与内核实现。
list(FILTER TFLM_CC_SOURCES EXCLUDE REGEX "_test\\.cc$|_testlib\\.cc$|/testing/|/examples/|/tools/|/benchmarks/|_annotate\\.|/integration_tests/|/arc_|/bluepill/|/chre/|/ceva/|/hexagon/|/xtensa/|/corstone_|cortex_m_corstone_300|/riscv32_|/msp430|/python/|/ethos_u\|cortex_m_generic/micro_time.cc")

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
        file(GLOB_RECURSE CMSIS_NN_LIB_SRCS ${TFLM_CMSIS_NN_DIR}/Source/*.c)
        # F16/F32 变体不参与（与上游 cmsis_nn.inc 的 ARM_NN_ENABLE_F16/F32=0 一致）
        list(FILTER CMSIS_NN_LIB_SRCS EXCLUDE REGEX "_f16\\.c$|_f32\\.c$|arm_nntables_flt\\.c$")

        # CMSIS-NN 内核与默认内核重复注册同名 op：按文件基名排除默认实现
        set(CMSIS_NN_RE "")
        foreach (f ${CMSIS_NN_KERNEL_SRCS})
            get_filename_component(b ${f} NAME_WE)
            if (CMSIS_NN_RE STREQUAL "")
                set(CMSIS_NN_RE "/${b}\\.cc$")
            else ()
                string(APPEND CMSIS_NN_RE "|/${b}\\.cc$")
            endif ()
        endforeach ()
        if (NOT CMSIS_NN_RE STREQUAL "")
            list(FILTER TFLM_CC_SOURCES EXCLUDE REGEX ${CMSIS_NN_RE})
        endif ()

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
    -fno-rtti
    -fno-exceptions
)

