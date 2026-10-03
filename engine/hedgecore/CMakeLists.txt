cmake_minimum_required(VERSION 3.24)
project(hedgecore LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

option(HEDGECORE_BUILD_TESTS "Build GoogleTest suite" ON)
option(HEDGECORE_BUILD_PYTHON "Build the pybind11 module" OFF)

add_library(hedgecore_lib STATIC src/engine.cpp)
target_include_directories(hedgecore_lib PUBLIC include)
target_compile_options(hedgecore_lib PRIVATE -Wall -Wextra -Wpedantic)

if(HEDGECORE_BUILD_TESTS)
  include(FetchContent)
  FetchContent_Declare(googletest
    URL https://github.com/google/googletest/archive/refs/tags/v1.15.2.tar.gz
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE)
  set(INSTALL_GTEST OFF CACHE BOOL "" FORCE)
  FetchContent_MakeAvailable(googletest)
  enable_testing()
  file(GLOB HEDGECORE_TEST_SOURCES CONFIGURE_DEPENDS ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_*.cpp)
  add_executable(hedgecore_tests ${HEDGECORE_TEST_SOURCES})
  target_compile_options(hedgecore_tests PRIVATE -Wall -Wextra -Wpedantic)
  target_link_libraries(hedgecore_tests PRIVATE hedgecore_lib GTest::gtest_main)
  include(GoogleTest)
  gtest_discover_tests(hedgecore_tests)
endif()

if(HEDGECORE_BUILD_PYTHON)
  find_package(Python REQUIRED COMPONENTS Interpreter Development.Module)
  find_package(pybind11 CONFIG REQUIRED)
  pybind11_add_module(hedgecore src/bindings.cpp)
  target_link_libraries(hedgecore PRIVATE hedgecore_lib)
  install(TARGETS hedgecore DESTINATION .)
endif()
