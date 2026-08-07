// Desk robot mechanical baseline. All dimensions are millimetres.
$fn = 48;
W = 280; D = 240; H = 330; WALL = 2.5; R = 18;

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
  translate([30,35,40]) cube([220,170,3]);
}

module wheels() {
  for (x=[50,230], y=[4,236])
    translate([x,y,43]) rotate([90,0,0]) cylinder(h=12,d=50,center=true);
}

module bumper() {
  difference() {
    translate([-8,-8,10]) rounded_box([W+16,D+16,42],R+8);
    translate([0,0,10]) rounded_box([W,D,43],R);
  }
}

color("LightGray",0.45) shell();
color("DimGray") chassis();
color("Black") wheels();
color("Orange",0.8) bumper();
