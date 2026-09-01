# frozen_string_literal: true

require "erb"

def assert_not_initialized(label)
  yield
  abort "#{label} unexpectedly evaluated a deserialized ERB object"
rescue ArgumentError => e
  abort "#{label} raised the wrong error: #{e.message}" unless e.message == "not initialized"
end

deserialized = ERB.allocate
deserialized.instance_variable_set(:@src, "end\nraise 'deserialized ERB executed'\ndef x")
deserialized.instance_variable_set(:@lineno, 1)
deserialized.instance_variable_set(:@_init, true)
deserialized = Marshal.load(Marshal.dump(deserialized))

assert_not_initialized("result") { deserialized.result }
assert_not_initialized("def_method") { deserialized.def_method(Class.new, "render") }
assert_not_initialized("def_module") { deserialized.def_module }
assert_not_initialized("def_class") { deserialized.def_class }

puts "ERB deserialization guards pass"
