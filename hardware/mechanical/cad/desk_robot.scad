// Workbench Desk Robot mechanical baseline, Revision B.
// All dimensions are millimetres. This model is an engineering visualization;
// production draft, ribs, bosses and tooling splits remain supplier-owned.
$fn = 64;

W = 280;
D = 240;
H = 330;
WALL = 2.5;
CHASSIS_W = 260;
CHASSIS_D = 220;
GROUND = 18;

BODY_Z = 30;
BODY_H = 70;
SHOULDER_Z = 92;
SHOULDER_TOP = 228;
HEAD_W = 190;
HEAD_D = 72;
HEAD_H = 92;
HEAD_TILT = 8;
SCREEN_W = 150;
SCREEN_H = 72;

module rounded_prism(w, d, h, r) {
  linear_extrude(height=h)
    offset(r=r)
      square([w-2*r, d-2*r], center=true);
}

module hollow_rounded_prism(w, d, h, r, wall) {
  difference() {
    rounded_prism(w, d, h, r);
    translate([0, 0, wall])
      rounded_prism(w-2*wall, d-2*wall, h, max(r-wall, 1));
  }
}

module low_chassis() {
  color([0.16, 0.18, 0.19])
    translate([0, 0, BODY_Z])
      hollow_rounded_prism(CHASSIS_W, CHASSIS_D, BODY_H, 20, WALL);

  // Recessed service datum and electronics tray.
  color([0.32, 0.35, 0.36])
    translate([0, 0, 43]) cube([220, 170, 3], center=true);
}

module shoulder_shell() {
  color([0.78, 0.80, 0.78])
    difference() {
      hull() {
        translate([0, 0, SHOULDER_Z]) rounded_prism(260, 220, 4, 20);
        translate([0, 0, SHOULDER_TOP-4]) rounded_prism(232, 190, 4, 16);
      }
      hull() {
        translate([0, 0, SHOULDER_Z+WALL]) rounded_prism(255, 215, 4, 17.5);
        translate([0, 0, SHOULDER_TOP-2]) rounded_prism(227, 185, 4, 13.5);
      }
    }

  // Rear service panel: separate, captive-fastener module.
  color([0.25, 0.28, 0.29])
    translate([0, D/2-9, 150]) cube([170, 5, 120], center=true);
  for (x=[-76, 76], z=[100, 200])
    color([0.55, 0.58, 0.58]) translate([x, D/2-12, z])
      rotate([90, 0, 0]) cylinder(h=4, d=6, center=true);
}

module neck_and_head() {
  // The narrow neck creates a clear head/body hierarchy and carries cables.
  color([0.22, 0.25, 0.26])
    translate([0, 4, 228]) rounded_prism(66, 58, 34, 12);
  color([0.08, 0.10, 0.11])
    translate([0, -25, 232]) cube([24, 12, 46], center=true);

  translate([0, -10, 264]) rotate([HEAD_TILT, 0, 0]) {
    color([0.88, 0.91, 0.89])
      difference() {
        rounded_prism(HEAD_W, HEAD_D, HEAD_H, 15);
        translate([0, -HEAD_D/2-1, 13])
          rotate([90, 0, 0]) cube([SCREEN_W+6, SCREEN_H+6, 8], center=true);
      }

    // Recessed dark lens and warm-white active display.
    color([0.025, 0.045, 0.055])
      translate([0, -HEAD_D/2-2.5, HEAD_H/2])
        rotate([90, 0, 0]) cube([SCREEN_W+6, SCREEN_H+6, 3], center=true);
    color([0.30, 0.82, 0.74])
      translate([0, -HEAD_D/2-4.2, HEAD_H/2])
        rotate([90, 0, 0]) cube([SCREEN_W, SCREEN_H, 1.2], center=true);
  }
}

module wheels_and_pods() {
  for (x=[-90, 90], y=[-CHASSIS_D/2-2, CHASSIS_D/2+2]) {
    color([0.06, 0.07, 0.07])
      translate([x, y, 43]) rotate([90, 0, 0]) cylinder(h=14, d=50, center=true);
    color([0.20, 0.22, 0.23])
      translate([x, y > 0 ? CHASSIS_D/2-5 : -CHASSIS_D/2+5, 60])
        rounded_prism(74, 22, 24, 10);
  }
}

module corner_bumpers() {
  // Four compact pads replace the visually heavy full-perimeter orange ring.
  for (x=[-W/2+26, W/2-26], y=[-D/2+22, D/2-22])
    color([0.20, 0.48, 0.45])
      translate([x, y, 30]) rounded_prism(42, 30, 28, 10);
}

module desk_robot_revision_b() {
  low_chassis();
  wheels_and_pods();
  corner_bumpers();
  shoulder_shell();
  neck_and_head();
}

desk_robot_revision_b();
