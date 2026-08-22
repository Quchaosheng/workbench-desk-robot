// Desk robot mechanical baseline. All dimensions are millimetres.
$fn = 48;
W = 280; D = 244; H = 330; WALL = 2.5; R = 18;
CHASSIS_W = 260; CHASSIS_D = 220; CHASSIS_BASE_Z = 22; CHASSIS_T = 4; CHASSIS_MOUNT_X = 121; CHASSIS_MOUNT_Y = 102.5;
MOTOR_ENV = [48,72,46]; MOTOR_X = 88; MOTOR_Z = 49;
MOTOR_BRACKET = [45,35,4]; MOTOR_UPRIGHT_T = 4; MOTOR_UPRIGHT_H = 46; MOTOR_UPRIGHT_Y = -15.5;
CHILDBOARD_ENV = [118,82,20]; CHILDBOARD_Y = 54; CHILDBOARD_Z = 151;
CHILDBOARD_SUPPORT_Z = 136; CHILDBOARD_SUPPORT_T = 3; CHILDBOARD_BASE_Z = 102; CHILDBOARD_BASE_POST_H = 32.5;
CHILDBOARD_STANDOFF = 3.5; CHILDBOARD_POST_D = 6;
// Keep the envelope and centre aligned with design-spec.json (centres use the
// chassis datum; this SCAD model translates that datum by W/2,D/2).
BATTERY_ENV = [80,100,40]; BATTERY_Y = 0; BATTERY_Z = 52;
MOTOR_OUTPUT_Y = 0; HUB_REAR_Y = 90; HUB_REAR_X = 105; HUB_REAR_Z = 43;
MOTOR_FACE_X = MOTOR_X + MOTOR_ENV[0]/2;
WHEEL_TRACK_HALF = 105; WHEELBASE_HALF = 90;

module rounded_box(size, radius) {
  hull() for (x=[radius, size[0]-radius], y=[radius, size[1]-radius])
    translate([x,y,radius]) sphere(radius);
}

module shell() {
  difference() {
    rounded_box([W,D,H], R);
    translate([WALL,WALL,WALL])
      rounded_box([W-2*WALL,D-2*WALL,H-WALL], R-WALL);
    translate([(W-150)/2,-1,225]) cube([150,WALL+2,72]);
    for (x=[42:28:238]) translate([x,D-4,260]) cube([14,8,42]);
  }
}

module chassis() {
  difference() {
    translate([(W-CHASSIS_W)/2,(D-CHASSIS_D)/2,CHASSIS_BASE_Z]) cube([CHASSIS_W,CHASSIS_D,CHASSIS_T]);
    for (x=[W/2-WHEEL_TRACK_HALF,W/2+WHEEL_TRACK_HALF], y=[D/2-WHEELBASE_HALF,D/2+WHEELBASE_HALF])
      translate([x,y,CHASSIS_BASE_Z+CHASSIS_T/2]) rotate([0,90,0]) cylinder(h=20,d=58,center=true);
  }
  for (x=[W/2-CHASSIS_MOUNT_X,W/2+CHASSIS_MOUNT_X], y=[D/2-CHASSIS_MOUNT_Y,D/2+CHASSIS_MOUNT_Y]) translate([x,y,26]) cylinder(h=20,d=8);
  // Keep the tray centred on the 244 mm enclosure datum (Y=122).
  translate([30,37,99]) cube([220,170,3]);
}

module wheels() {
  // Wheel axle is lateral X.  The ground contact lies at Z=18 and rolls in -Y.
  for (x=[W/2-WHEEL_TRACK_HALF,W/2+WHEEL_TRACK_HALF], y=[D/2-WHEELBASE_HALF,D/2+WHEELBASE_HALF])
    translate([x,y,43]) rotate([0,90,0]) cylinder(h=12,d=50,center=true);
}

module bumper() {
  difference() {
    translate([-8,-8,10]) rounded_box([W+16,D+16,42],R+8);
    translate([0,0,10]) rounded_box([W,D,43],R);
  }
}

module traction_motor_envelope(x_position) {
  translate([W/2+x_position-MOTOR_ENV[0]/2,D/2-MOTOR_ENV[1]/2,MOTOR_Z-MOTOR_ENV[2]/2])
    cube(MOTOR_ENV);
}

module traction_motor_bracket(x_position) {
  translate([W/2+x_position-MOTOR_BRACKET[0]/2,D/2-MOTOR_BRACKET[1]/2,CHASSIS_BASE_Z+CHASSIS_T])
    cube(MOTOR_BRACKET);
  translate([W/2+x_position-MOTOR_BRACKET[0]/2,D/2+MOTOR_UPRIGHT_Y-MOTOR_UPRIGHT_T/2,CHASSIS_BASE_Z+CHASSIS_T])
    cube([MOTOR_BRACKET[0],MOTOR_UPRIGHT_T,MOTOR_UPRIGHT_H]);
}

module traction_childboard_envelope() {
  translate([W/2-CHILDBOARD_ENV[0]/2,D/2+CHILDBOARD_Y-CHILDBOARD_ENV[1]/2,CHILDBOARD_Z-CHILDBOARD_ENV[2]/2])
    cube(CHILDBOARD_ENV);
}

module traction_childboard_support() {
  translate([W/2-CHILDBOARD_ENV[0]/2,D/2+CHILDBOARD_Y-CHILDBOARD_ENV[1]/2,CHILDBOARD_SUPPORT_Z-CHILDBOARD_SUPPORT_T/2])
    cube([CHILDBOARD_ENV[0],CHILDBOARD_ENV[1],CHILDBOARD_SUPPORT_T]);
  for (x=[-54,54], y=[-36,36]) {
    translate([W/2+x,D/2+CHILDBOARD_Y+y,CHILDBOARD_BASE_Z])
      cylinder(h=CHILDBOARD_BASE_POST_H,d=CHILDBOARD_POST_D);
    translate([W/2+x,D/2+CHILDBOARD_Y+y,CHILDBOARD_SUPPORT_Z+CHILDBOARD_SUPPORT_T/2])
      cylinder(h=CHILDBOARD_STANDOFF,d=CHILDBOARD_POST_D);
  }
}

module battery_envelope() {
  translate([W/2-BATTERY_ENV[0]/2,D/2+BATTERY_Y-BATTERY_ENV[1]/2,BATTERY_Z-BATTERY_ENV[2]/2])
    cube(BATTERY_ENV);
}

// Review-only drivetrain datums. These rods mark the declared lateral output/hub axes
// and nominal offset path; they are not a selected shaft, belt, gear, or bearing.
module drivetrain_datums(side) {
  motor_x = W/2 + side*MOTOR_FACE_X;
  hub_x = W/2 + side*HUB_REAR_X;
  motor_y = D/2 + MOTOR_OUTPUT_Y;
  hub_y = D/2 + HUB_REAR_Y;
  motor_z = MOTOR_Z;
  hub_z = HUB_REAR_Z;
  color("SlateGray",0.65) {
    translate([motor_x,motor_y,motor_z]) rotate([0,90,0]) cylinder(h=10,d=8,center=true);
    translate([hub_x,hub_y,hub_z]) rotate([0,90,0]) cylinder(h=16,d=10,center=true);
    hull() {
      translate([motor_x,motor_y,motor_z]) sphere(d=3);
      translate([hub_x,hub_y,hub_z]) sphere(d=3);
    }
  }
}

color("LightGray",0.45) shell();
color("DimGray") chassis();
color("Black") wheels();
color("Orange",0.8) bumper();
color("DarkOrange",0.35) traction_motor_envelope(-MOTOR_X);
color("DarkOrange",0.35) traction_motor_envelope(MOTOR_X);
color("SaddleBrown",0.85) traction_motor_bracket(-MOTOR_X);
color("SaddleBrown",0.85) traction_motor_bracket(MOTOR_X);
drivetrain_datums(-1);
drivetrain_datums(1);
color("Gray",0.8) traction_childboard_support();
color("SeaGreen",0.35) traction_childboard_envelope();
color("RoyalBlue",0.25) battery_envelope();
