// Workbench Home Robot mechanical concept, Revision D.
// Dual seven-axis mobile manipulator with a braked lifting platform.
// Dimensions are millimetres; physical validation remains required.
$fn = 56;

BASE_W = 540;
BASE_D = 520;
BASE_H = 112;
GROUND = 28;
LIFT_TRAVEL = 350;
LIFT_EXTENSION = LIFT_TRAVEL; // generated package is the raised working pose
BASE_TOP = GROUND + BASE_H;
TORSO_BOTTOM_STOWED = 500;
TORSO_BOTTOM = TORSO_BOTTOM_STOWED + LIFT_EXTENSION;
TORSO_W = 420;
TORSO_D = 330;
TORSO_H = 430;
HEAD_W = 260;
HEAD_D = 105;
HEAD_H = 128;
HEAD_TILT = 6;
HEAD_TOP_STOWED = 1100;
HEAD_TOP = HEAD_TOP_STOWED + LIFT_EXTENSION;
HEAD_MODEL_Z = HEAD_TOP - (HEAD_H*cos(HEAD_TILT) + HEAD_D/2*sin(HEAD_TILT));
HEAD_BOTTOM = HEAD_MODEL_Z - HEAD_D/2*sin(HEAD_TILT);
STABILIZERS_DEPLOYED = false;

module rounded_prism(w, d, h, r) {
  linear_extrude(height=h)
    offset(r=r)
      square([w-2*r, d-2*r], center=true);
}

module faired_link(a, b, w1, d1, w2, d2, gap=18, radius=15) {
  v = b-a;
  length = norm(v);
  axis = cross([0, 0, 1], v);
  angle = acos(v[2]/length);
  color([0.88, 0.87, 0.83])
    translate(a)
      rotate(a=angle, v=axis)
        translate([0, 0, gap])
          linear_extrude(
            height=length-2*gap,
            scale=[w2/w1, d2/d1]
          )
            offset(r=radius)
              square([w1-2*radius, d1-2*radius], center=true);
}

module joint_cartridge(pos, diameter, axis_rotation=[0, 0, 0]) {
  translate(pos) rotate(axis_rotation) {
    color([0.07, 0.08, 0.08])
      cylinder(h=diameter*0.62, d=diameter, center=true);
    color([0.38, 0.41, 0.39])
      for (z=[-diameter*0.33, diameter*0.33])
        translate([0, 0, z]) cylinder(h=diameter*0.10, d=diameter*1.08, center=true);
    color([0.44, 0.76, 0.68])
      translate([0, 0, diameter*0.39]) cylinder(h=2, d=diameter*0.34, center=true);
  }
}

module mobile_base() {
  color([0.12, 0.14, 0.14])
    translate([0, 0, GROUND]) rounded_prism(BASE_W, BASE_D, BASE_H, 50);
  color([0.34, 0.36, 0.35])
    translate([0, 0, GROUND+BASE_H-10]) rounded_prism(480, 420, 18, 36);

  // Four independent steer-drive modules support holonomic self-motion.
  // Each module has a visible wheel, vertical steering bearing and local fork.
  for (x=[-195, 195], y=[-185, 185]) {
    color([0.24, 0.27, 0.26])
      translate([x, y, 100]) cylinder(h=34, d=62, center=true);
    color([0.12, 0.14, 0.14])
      translate([x, y, 76]) rounded_prism(62, 58, 42, 14);
    color([0.035, 0.04, 0.04])
      translate([x, y, 70]) rotate([0, 90, 18]) cylinder(h=42, d=140, center=true);
    color([0.42, 0.44, 0.42])
      translate([x, y, 70]) rotate([0, 90, 18]) cylinder(h=46, d=48, center=true);
  }

  // The perimeter bumper is structural and sits above the wheel contact plane.
  color([0.035, 0.04, 0.04])
    translate([0, 0, GROUND+58]) rounded_prism(512, 492, 28, 44);

  // Stabilizers are flush in navigation and only deploy for manipulation.
  for (x=[-386, 386], y=[-386, 386])
    if (STABILIZERS_DEPLOYED)
      color([0.10, 0.11, 0.11])
        translate([x, y, GROUND+10]) rounded_prism(48, 48, 18, 12);
    else
      color([0.18, 0.20, 0.19])
        translate([x*0.59, y*0.58, GROUND+72]) rounded_prism(46, 46, 18, 12);
}

module lifting_platform() {
  color([0.10, 0.12, 0.12])
    translate([0, 12, BASE_TOP]) rounded_prism(210, 175, TORSO_BOTTOM_STOWED-BASE_TOP, 24);
  color([0.34, 0.36, 0.35])
    translate([0, 12, TORSO_BOTTOM-360]) rounded_prism(170, 138, 350, 20);
  color([0.16, 0.18, 0.18])
    for (z=[GROUND+BASE_H+28:28:GROUND+BASE_H+LIFT_EXTENSION-4])
      translate([0, -79, z]) cube([190, 10, 13], center=true);
  color([0.42, 0.44, 0.42])
    translate([0, 12, TORSO_BOTTOM-28]) rounded_prism(270, 228, 28, 28);
}

module utility_torso() {
  body_z = TORSO_BOTTOM;
  color([0.92, 0.91, 0.87])
    hull() {
      translate([0, 0, body_z]) rounded_prism(TORSO_W, TORSO_D, 8, 42);
      translate([0, 0, body_z+TORSO_H-8]) rounded_prism(292, 248, 8, 38);
    }

  // Soft-close parcel bay and acoustic insert share one graphite plane.
  color([0.12, 0.14, 0.14])
    translate([0, -TORSO_D/2-3, body_z+150])
      rotate([90, 0, 0]) rounded_prism(224, 126, 8, 20);
  color([0.34, 0.36, 0.35])
    translate([0, 0, body_z-8]) rounded_prism(310, 265, 22, 34);

  // Rear structural spine carries the arm load into the lift, not the plastic shell.
  color([0.28, 0.30, 0.29])
    translate([128, 62, body_z+60]) rounded_prism(74, 96, 286, 26);
}

module neck_mount(head_z) {
  // The head seats on a broad shoulder plate and keyed locating register.
  // Four captive M6 fasteners enter from below; the centre stays open for loom routing.
  difference() {
    union() {
      color([0.30, 0.32, 0.31])
        translate([0, 12, head_z-80]) rounded_prism(132, 86, 72, 24);
      color([0.22, 0.24, 0.23])
        translate([0, 12, head_z-18]) rounded_prism(184, 74, 10, 14);
      color([0.38, 0.41, 0.39])
        translate([0, 12, head_z-8]) rounded_prism(154, 58, 8, 12);
    }
    translate([0, 12, head_z-60]) cylinder(h=100, d=32);
    for (x=[-48, 48], y=[-22, 22])
      translate([x, 12+y, head_z-34]) cylinder(h=36, d=6.8);
    for (x=[-60, 60])
      translate([x, 12, head_z-18]) cylinder(h=18, d=4.1);
  }
}

module head_and_face() {
  neck_mount(HEAD_BOTTOM);
  translate([0, -12, HEAD_MODEL_Z]) rotate([HEAD_TILT, 0, 0]) {
    color([0.92, 0.91, 0.87]) rounded_prism(HEAD_W, HEAD_D, HEAD_H, 32);
    color([0.025, 0.035, 0.035])
      translate([0, -HEAD_D/2-4, 20])
        rotate([90, 0, 0]) rounded_prism(228, 92, 7, 24);
    color([0.44, 0.79, 0.70])
      for (x=[-38, 38])
        translate([x, -HEAD_D/2-8, 42]) rotate([90, 0, 0]) cylinder(h=2, d=12, center=true);
  }
}

module seven_axis_arm(side=1) {
  // The three-axis shoulder is nested in the torso side wall. Directional
  // fairings cover the primary links; dark bearing cartridges and 6 mm motion
  // gaps keep the seven-axis assembly and service order visually legible.
  arm_base_z = TORSO_BOTTOM + 160;
  p1 = [side*176, 118, arm_base_z];
  p2 = [side*204, 88, arm_base_z-12];
  p3 = [side*250, 48, arm_base_z-40];
  p4 = [side*375, -105, arm_base_z-145];
  p5 = [side*330, -245, arm_base_z-210];
  p6 = [side*270, -295, arm_base_z-230];
  p7 = [side*225, -318, arm_base_z-242];
  ee = [side*182, -335, arm_base_z-250];

  // Shoulder bridge, tapered upper arm, tapered forearm and compact wrist.
  faired_link(p1, p2, 72, 66, 66, 60, 12, 20);
  faired_link(p2, p3, 66, 60, 60, 54, 12, 18);
  faired_link(p3, p4, 78, 68, 64, 58, 24, 20);
  faired_link(p4, p5, 66, 58, 52, 48, 22, 17);
  faired_link(p5, p6, 44, 42, 38, 36, 16, 13);
  faired_link(p6, p7, 38, 34, 32, 30, 13, 11);
  faired_link(p7, ee, 30, 28, 24, 24, 11, 9);

  joint_cartridge(p1, 82, [0, 0, 0]);
  joint_cartridge(p2, 68, [90, 0, 0]);
  joint_cartridge(p3, 58, [0, 90, 0]);
  joint_cartridge(p4, 54, [90, 0, 0]);
  joint_cartridge(p5, 42, [0, 90, 0]);
  joint_cartridge(p6, 34, [90, 0, 0]);
  joint_cartridge(p7, 30, [0, 90, 0]);

  // Kinematic quick-change and adaptive gripper.
  color([0.72, 0.74, 0.71]) translate(ee) sphere(d=28);
  color([0.09, 0.10, 0.10])
    for (x=[-14, 14])
      translate([ee[0]+x, ee[1]-20, ee[2]-20])
        rotate([18, 0, 0]) rounded_prism(10, 14, 62, 5);
}

module dual_seven_axis_arms() {
  seven_axis_arm(-1);
  seven_axis_arm(1);
}

module tool_dock() {
  // Cleaning and food-contact tools are removable and segregated.
  color([0.26, 0.28, 0.27])
    translate([-178, 86, TORSO_BOTTOM]) rounded_prism(62, 160, 230, 22);
  color([0.68, 0.70, 0.66])
    for (z=[TORSO_BOTTOM+40, TORSO_BOTTOM+110, TORSO_BOTTOM+180])
      translate([-211, 44, z]) rotate([0, 90, 0]) cylinder(h=34, d=28, center=true);
}

module workbench_home_robot_revision_d() {
  mobile_base();
  lifting_platform();
  utility_torso();
  head_and_face();
  dual_seven_axis_arms();
  tool_dock();
}

workbench_home_robot_revision_d();
