#include <fcntl.h>
#include <unistd.h>

#include <array>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <iomanip>
#include <iostream>
#include <memory>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include <rapidjson/stringbuffer.h>
#include <rapidjson/writer.h>
#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/joint_state.hpp>
#include <tf2_msgs/msg/tf_message.hpp>

namespace
{
using JsonWriter = rapidjson::Writer<rapidjson::StringBuffer>;

constexpr char kJointPublisher[] = "/joint_state_publisher";
constexpr char kTfPublisher[] = "/robot_state_publisher";

struct SampleIdentity
{
  std::string publisher_name;
  std::string publisher_gid;
  int64_t source_timestamp_ns;
  int64_t received_timestamp_ns;
  uint64_t publication_sequence_number;
};

std::string gid_hex(const uint8_t * data, std::size_t size)
{
  std::ostringstream stream;
  stream << std::hex << std::setfill('0');
  for (std::size_t index = 0; index < size; ++index) {
    stream << std::setw(2) << static_cast<unsigned int>(data[index]);
  }
  return stream.str();
}

std::string endpoint_name(const rclcpp::TopicEndpointInfo & endpoint)
{
  const auto & namespace_name = endpoint.node_namespace();
  if (namespace_name == "/") {
    return "/" + endpoint.node_name();
  }
  return namespace_name + "/" + endpoint.node_name();
}

void write_identity(JsonWriter & writer, const SampleIdentity & identity)
{
  writer.Key("publisher_name");
  writer.String(identity.publisher_name.c_str());
  writer.Key("publisher_gid");
  writer.String(identity.publisher_gid.c_str());
  writer.Key("source_timestamp_ns");
  writer.Int64(identity.source_timestamp_ns);
  writer.Key("received_timestamp_ns");
  writer.Int64(identity.received_timestamp_ns);
  writer.Key("publication_sequence_number");
  writer.Uint64(identity.publication_sequence_number);
}

void write_stamp(JsonWriter & writer, const builtin_interfaces::msg::Time & stamp)
{
  writer.Key("sec");
  writer.Int(stamp.sec);
  writer.Key("nanosec");
  writer.Uint(stamp.nanosec);
}

class ProvenanceCollector : public rclcpp::Node
{
public:
  ProvenanceCollector()
  : Node("c3a_sample_provenance")
  {
    output_path_ = declare_parameter<std::string>("output_path");
    request_path_ = declare_parameter<std::string>("request_path");
    timeout_s_ = declare_parameter<double>("timeout_s", 10.0);
    if (output_path_.empty() || request_path_.empty() ||
      !std::filesystem::path(output_path_).is_absolute() ||
      !std::filesystem::path(request_path_).is_absolute())
    {
      throw std::invalid_argument("output_path and request_path must be absolute");
    }
    if (!(timeout_s_ > 0.0)) {
      throw std::invalid_argument("timeout_s must be positive");
    }

    joint_subscription_ = create_subscription<sensor_msgs::msg::JointState>(
      "/joint_states", rclcpp::SensorDataQoS(),
      [this](sensor_msgs::msg::JointState::ConstSharedPtr message, const rclcpp::MessageInfo & info) {
        try {
          if (!arm_if_requested()) {
            return;
          }
          const auto identity = bind_identity("/joint_states", kJointPublisher, info);
          if (identity.received_timestamp_ns <= *armed_at_ns_) {
            return;
          }
          joint_identity_ = identity;
          joint_state_ = std::move(message);
          finish_if_ready();
        } catch (const std::exception & error) {
          fail(error.what());
        }
      });

    auto dynamic_qos = rclcpp::QoS(rclcpp::KeepLast(100)).durability_volatile();
    dynamic_tf_subscription_ = create_subscription<tf2_msgs::msg::TFMessage>(
      "/tf", dynamic_qos,
      [this](tf2_msgs::msg::TFMessage::ConstSharedPtr message, const rclcpp::MessageInfo & info) {
        try {
          if (!arm_if_requested()) {
            return;
          }
          const auto identity = bind_identity("/tf", kTfPublisher, info);
          if (identity.received_timestamp_ns <= *armed_at_ns_) {
            return;
          }
          dynamic_tf_identity_ = identity;
          dynamic_tf_ = std::move(message);
          finish_if_ready();
        } catch (const std::exception & error) {
          fail(error.what());
        }
      });

    auto static_qos = rclcpp::QoS(rclcpp::KeepLast(100)).transient_local();
    static_tf_subscription_ = create_subscription<tf2_msgs::msg::TFMessage>(
      "/tf_static", static_qos,
      [this](tf2_msgs::msg::TFMessage::ConstSharedPtr message, const rclcpp::MessageInfo & info) {
        try {
          static_tf_identity_ = bind_identity("/tf_static", kTfPublisher, info);
          static_tf_ = std::move(message);
          if (arm_if_requested()) {
            finish_if_ready();
          }
        } catch (const std::exception & error) {
          fail(error.what());
        }
      });

    deadline_ = create_wall_timer(
      std::chrono::duration<double>(timeout_s_), [this]() {fail("sample provenance deadline expired");});
  }

  bool succeeded() const {return succeeded_;}

private:
  bool arm_if_requested()
  {
    if (armed_) {
      return true;
    }
    std::error_code error;
    const auto status = std::filesystem::status(request_path_, error);
    if (error) {
      if (error == std::errc::no_such_file_or_directory) {
        return false;
      }
      throw std::runtime_error("could not inspect provenance request marker: " + error.message());
    }
    if (status.type() == std::filesystem::file_type::not_found) {
      return false;
    }
    if (!std::filesystem::is_regular_file(status)) {
      throw std::runtime_error("provenance request marker is not a regular file");
    }
    joint_state_.reset();
    dynamic_tf_.reset();
    joint_identity_.reset();
    dynamic_tf_identity_.reset();
    armed_at_ns_ = std::chrono::duration_cast<std::chrono::nanoseconds>(
      std::chrono::system_clock::now().time_since_epoch()).count();
    armed_ = true;
    return true;
  }

  SampleIdentity bind_identity(
    const std::string & topic, const std::string & expected_name, const rclcpp::MessageInfo & info)
  {
    const auto endpoints = get_publishers_info_by_topic(topic);
    if (endpoints.size() != 1 || endpoint_name(endpoints.front()) != expected_name) {
      throw std::runtime_error("uncontrolled publisher set for " + topic);
    }
    const auto & rmw_info = info.get_rmw_message_info();
    const auto sample_gid = gid_hex(rmw_info.publisher_gid.data, RMW_GID_STORAGE_SIZE);
    const auto & endpoint_gid = endpoints.front().endpoint_gid();
    if (sample_gid != gid_hex(endpoint_gid.data(), endpoint_gid.size())) {
      throw std::runtime_error("sample writer GID does not match graph endpoint for " + topic);
    }
    if (rmw_info.source_timestamp <= 0 || rmw_info.received_timestamp <= 0 ||
      rmw_info.received_timestamp < rmw_info.source_timestamp)
    {
      throw std::runtime_error("sample middleware timestamps are malformed for " + topic);
    }
    return SampleIdentity{
      expected_name, sample_gid, rmw_info.source_timestamp, rmw_info.received_timestamp,
      rmw_info.publication_sequence_number};
  }

  static void write_transform(JsonWriter & writer, const geometry_msgs::msg::TransformStamped & transform)
  {
    writer.StartObject();
    writer.Key("header");
    writer.StartObject();
    write_stamp(writer, transform.header.stamp);
    writer.Key("frame_id");
    writer.String(transform.header.frame_id.c_str());
    writer.EndObject();
    writer.Key("child_frame_id");
    writer.String(transform.child_frame_id.c_str());
    writer.Key("translation");
    writer.StartArray();
    writer.Double(transform.transform.translation.x);
    writer.Double(transform.transform.translation.y);
    writer.Double(transform.transform.translation.z);
    writer.EndArray();
    writer.Key("rotation");
    writer.StartArray();
    writer.Double(transform.transform.rotation.x);
    writer.Double(transform.transform.rotation.y);
    writer.Double(transform.transform.rotation.z);
    writer.Double(transform.transform.rotation.w);
    writer.EndArray();
    writer.EndObject();
  }

  static void write_tf_sample(
    JsonWriter & writer, const tf2_msgs::msg::TFMessage & message, const SampleIdentity & identity)
  {
    writer.StartObject();
    write_identity(writer, identity);
    writer.Key("transforms");
    writer.StartArray();
    for (const auto & transform : message.transforms) {
      write_transform(writer, transform);
    }
    writer.EndArray();
    writer.EndObject();
  }

  std::string encode() const
  {
    rapidjson::StringBuffer buffer;
    JsonWriter writer(buffer);
    writer.StartObject();
    writer.Key("schema_version");
    writer.String("c3a-rmw-sample-provenance-1");
    writer.Key("armed_at_ns");
    writer.Int64(*armed_at_ns_);
    writer.Key("joint_state");
    writer.StartObject();
    write_identity(writer, *joint_identity_);
    writer.Key("header");
    writer.StartObject();
    write_stamp(writer, joint_state_->header.stamp);
    writer.EndObject();
    writer.Key("name");
    writer.StartArray();
    for (const auto & name : joint_state_->name) {
      writer.String(name.c_str());
    }
    writer.EndArray();
    writer.Key("position");
    writer.StartArray();
    for (const auto position : joint_state_->position) {
      writer.Double(position);
    }
    writer.EndArray();
    writer.EndObject();
    writer.Key("tf");
    write_tf_sample(writer, *dynamic_tf_, *dynamic_tf_identity_);
    writer.Key("tf_static");
    write_tf_sample(writer, *static_tf_, *static_tf_identity_);
    writer.EndObject();
    return std::string(buffer.GetString(), buffer.GetSize());
  }

  void finish_if_ready()
  {
    if (finished_ || !armed_ || !joint_state_ || !dynamic_tf_ || !static_tf_) {
      return;
    }
    const auto payload = encode();
    const int descriptor = open(output_path_.c_str(), O_WRONLY | O_CREAT | O_EXCL, 0600);
    if (descriptor < 0) {
      fail("could not create provenance artifact: " + std::string(std::strerror(errno)));
      return;
    }
    const auto written = write(descriptor, payload.data(), payload.size());
    const bool valid = written == static_cast<ssize_t>(payload.size()) && fsync(descriptor) == 0;
    close(descriptor);
    if (!valid) {
      unlink(output_path_.c_str());
      fail("could not persist complete provenance artifact");
      return;
    }
    if (unlink(request_path_.c_str()) < 0 && errno != ENOENT) {
      unlink(output_path_.c_str());
      fail("could not remove provenance request marker: " + std::string(std::strerror(errno)));
      return;
    }
    succeeded_ = true;
    finished_ = true;
    rclcpp::shutdown();
  }

  void fail(const std::string & reason)
  {
    if (finished_) {
      return;
    }
    RCLCPP_ERROR(get_logger(), "%s", reason.c_str());
    unlink(output_path_.c_str());
    unlink(request_path_.c_str());
    finished_ = true;
    rclcpp::shutdown();
  }

  std::string output_path_;
  std::string request_path_;
  double timeout_s_{0.0};
  bool armed_{false};
  std::optional<int64_t> armed_at_ns_;
  bool succeeded_{false};
  bool finished_{false};
  sensor_msgs::msg::JointState::ConstSharedPtr joint_state_;
  tf2_msgs::msg::TFMessage::ConstSharedPtr dynamic_tf_;
  tf2_msgs::msg::TFMessage::ConstSharedPtr static_tf_;
  std::optional<SampleIdentity> joint_identity_;
  std::optional<SampleIdentity> dynamic_tf_identity_;
  std::optional<SampleIdentity> static_tf_identity_;
  rclcpp::Subscription<sensor_msgs::msg::JointState>::SharedPtr joint_subscription_;
  rclcpp::Subscription<tf2_msgs::msg::TFMessage>::SharedPtr dynamic_tf_subscription_;
  rclcpp::Subscription<tf2_msgs::msg::TFMessage>::SharedPtr static_tf_subscription_;
  rclcpp::TimerBase::SharedPtr deadline_;
};
}  // namespace

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  try {
    auto collector = std::make_shared<ProvenanceCollector>();
    rclcpp::spin(collector);
    return collector->succeeded() ? 0 : 1;
  } catch (const std::exception & error) {
    std::cerr << "C3a provenance collector failed: " << error.what() << std::endl;
    if (rclcpp::ok()) {
      rclcpp::shutdown();
    }
    return 2;
  }
}
