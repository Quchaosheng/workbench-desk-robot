// Desk robot mechanical baseline. All dimensions are millimetres.
$fn = 48;
W = 280; D = 240; H = 330; WALL = 2.5; R = 18;
MOTOR_ENV = [48,72,46]; MOTOR_X = 86; MOTOR_Z = 49;
CHILDBOARD_ENV = [118,82,20]; CHILDBOARD_Y = 54; CHILDBOARD_Z = 150;
BATTERY_ENV = [160,100,50]; BATTERY_Y = -25; BATTERY_Z = 52;

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
  translate([10,10,22]) cube([260,220,4]);
  for (x=[32,248], y=[38,202]) translate([x,y,26]) cylinder(h=20,d=8);
  translate([30,35,99]) cube([220,170,3]);
}

module wheels() {
  for (x=[50,230], y=[15,225])
    translate([x,y,43]) rotate([90,0,0]) cylinder(h=12,d=50,center=true);
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

module traction_childboard_envelope() {
  translate([W/2-CHILDBOARD_ENV[0]/2,D/2+CHILDBOARD_Y-CHILDBOARD_ENV[1]/2,CHILDBOARD_Z-CHILDBOARD_ENV[2]/2])
    cube(CHILDBOARD_ENV);
}

module battery_envelope() {
  translate([W/2-BATTERY_ENV[0]/2,D/2+BATTERY_Y-BATTERY_ENV[1]/2,BATTERY_Z-BATTERY_ENV[2]/2])
    cube(BATTERY_ENV);
}

color("LightGray",0.45) shell();
color("DimGray") chassis();
color("Black") wheels();
color("Orange",0.8) bumper();
color("DarkOrange",0.35) traction_motor_envelope(-MOTOR_X);
color("DarkOrange",0.35) traction_motor_envelope(MOTOR_X);
color("SeaGreen",0.35) traction_childboard_envelope();
color("RoyalBlue",0.25) battery_envelope();
