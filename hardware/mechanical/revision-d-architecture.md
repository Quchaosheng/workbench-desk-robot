# Revision D bimanual mobile architecture

Revision D is a wheeled household mobile manipulator with two seven-axis arms, a liftable torso, and a perception/interaction head. The architecture is informed by public systems including [Mobile ALOHA](https://mobile-aloha.github.io/) and [PAL Robotics TIAGo](https://pal-robotics.com/robot/tiago/): useful household work needs bimanual whole-body coordination, a mobile base, a vertically adjustable manipulation frame, and explicit shared-workspace control.

Each arm has seven revolute axes excluding the gripper. The structural shoulder yokes sit in the upper torso side walls and attach to the lift-supported metal spine, not the cosmetic shell. The head has a separate rounded neck and is never supported by either arm. Its circular smoked-glass expression window keeps the domestic product visually soft. The left and right arms each have an exclusive workspace, a shared bimanual volume in front of the parcel bay, and forbidden volumes around the opposite shoulder, head, lift column, and tool dock. Entry into the shared volume requires one coordinator and reduced speed.

The 350 mm lift moves both shoulders, head, and tool frame between low navigation and raised counter-work poses. The battery, drive, and ballast remain in the base. Manipulation outside the navigation envelope requires wheel brakes and deployed stabilizers. Maximum-height, dual-payload, emergency-stop, slope, and floor-friction cases remain physical validation gates.

Target household tasks are bimanual parcel pickup/carry, cabinet and container handling, cleaning-tool changes, and supervised induction-cooking assistance. The robot may hold a vessel or fixture with one arm while stirring or turning with the other. Open flame, hot-pan transport, boiling-liquid carry, stairs, person lifting, and unattended hot work remain prohibited.

Status: `CONCEPT_PHYSICAL_VALIDATION_REQUIRED`.
