cmake_minimum_required(VERSION 3.16)
project(workbench_motion_provenance)

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(tf2_msgs REQUIRED)
find_package(RapidJSON REQUIRED)

add_executable(c3a_sample_provenance src/c3a_sample_provenance.cpp)
target_compile_features(c3a_sample_provenance PRIVATE cxx_std_17)
target_include_directories(c3a_sample_provenance PRIVATE ${RapidJSON_INCLUDE_DIRS})
ament_target_dependencies(c3a_sample_provenance geometry_msgs rclcpp sensor_msgs tf2_msgs)

install(TARGETS c3a_sample_provenance DESTINATION lib/${PROJECT_NAME})

ament_package()
