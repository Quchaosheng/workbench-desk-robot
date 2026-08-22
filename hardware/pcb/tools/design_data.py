from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Pin:
    number: str
    name: str
    side: str


@dataclass(frozen=True)
class Component:
    reference: str
    symbol: str
    value: str
    footprint: str
    block: str
    pins: dict[str, str | None]
    mpn: str = ""
    datasheet: str = ""
    note: str = ""
    dnp: bool = False


def box_pins(left: list[tuple[str, str]], right: list[tuple[str, str]]) -> list[Pin]:
    return [
        *(Pin(number, name, "left") for number, name in left),
        *(Pin(number, name, "right") for number, name in right),
    ]


MCU_PIN_NAMES = {
    1: "PE2",
    2: "PE3",
    3: "PE4",
    4: "PE5",
    5: "PE6",
    6: "VBAT",
    7: "PC13",
    8: "PC14",
    9: "PC15",
    10: "VSS",
    11: "VDD",
    12: "OSC_IN",
    13: "OSC_OUT",
    14: "NRST",
    15: "PC0",
    16: "PC1",
    17: "PC2",
    18: "PC3",
    19: "VSSA",
    20: "VREF-",
    21: "VREF+",
    22: "VDDA",
    23: "PA0",
    24: "PA1",
    25: "PA2",
    26: "PA3",
    27: "VSS",
    28: "VDD",
    29: "PA4",
    30: "PA5/SPI1_SCK",
    31: "PA6/SPI1_MISO",
    32: "PA7/SPI1_MOSI",
    33: "PC4",
    34: "PC5",
    35: "PB0",
    36: "PB1",
    37: "PB2",
    38: "PE7",
    39: "PE8",
    40: "PE9",
    41: "PE10",
    42: "PE11",
    43: "PE12",
    44: "PE13",
    45: "PE14",
    46: "PE15",
    47: "PB10",
    48: "PB11",
    49: "VSS",
    50: "VIO",
    51: "PB12",
    52: "PB13",
    53: "PB14",
    54: "PB15",
    55: "PD8",
    56: "PD9",
    57: "PD10",
    58: "PD11",
    59: "PD12",
    60: "PD13",
    61: "PD14",
    62: "PD15",
    63: "PC6",
    64: "PC7",
    65: "PC8",
    66: "PC9",
    67: "PA8",
    68: "PA9/USART1_TX",
    69: "PA10/USART1_RX",
    70: "PA11",
    71: "PA12",
    72: "SWDIO",
    73: "NC",
    74: "VSS",
    75: "VDD",
    76: "SWCLK",
    77: "PA15",
    78: "PC10",
    79: "PC11",
    80: "PC12",
    81: "PD0/CAN1_RX",
    82: "PD1/CAN1_TX",
    83: "PD2",
    84: "PD3",
    85: "PD4",
    86: "PD5",
    87: "PD6",
    88: "PD7",
    89: "PB3",
    90: "PB4",
    91: "PB5",
    92: "PB6/I2C1_SCL",
    93: "PB7/I2C1_SDA",
    94: "BOOT0",
    95: "PB8",
    96: "PB9",
    97: "PE0",
    98: "PE1",
    99: "VSS",
    100: "VIO",
}


CUSTOM_SYMBOLS: dict[str, tuple[str, list[Pin]]] = {
    "CONN_2": ("J", box_pins([("1", "1")], [("2", "2")])),
    "CONN_4": ("J", box_pins([("1", "1"), ("2", "2")], [("3", "3"), ("4", "4")])),
    "CONN_20": (
        "J",
        box_pins(
            [(str(index), str(index)) for index in range(1, 11)], [(str(index), str(index)) for index in range(11, 21)]
        ),
    ),
    "FUSE": ("F", box_pins([("1", "IN")], [("2", "OUT")])),
    "RESISTOR": ("R", box_pins([("1", "1")], [("2", "2")])),
    "CAPACITOR": ("C", box_pins([("1", "+")], [("2", "-")])),
    "DIODE": ("D", box_pins([("1", "K")], [("2", "A")])),
    "NMOS": ("Q", box_pins([("1", "G"), ("2", "S")], [("3", "D")])),
    "CRYSTAL": ("Y", box_pins([("1", "1")], [("2", "2")])),
    "LTC4368": (
        "U",
        box_pins(
            [("1", "GND"), ("2", "RETRY"), ("3", "OV"), ("4", "UV"), ("5", "VIN")],
            [("10", "GATE"), ("9", "SENSE"), ("8", "VOUT"), ("7", "FAULT"), ("6", "SHDN")],
        ),
    ),
    "ISOLATED_DC_DC_TBD": (
        "U",
        box_pins(
            [("1", "+IN"), ("2", "-IN"), ("3", "ENABLE"), ("7", "AUX1"), ("8", "AUX2")],
            [("4", "+OUT"), ("5", "-OUT"), ("6", "TRIM"), ("9", "AUX3")],
        ),
    ),
    "TPS26633RGE": (
        "U",
        box_pins(
            [
                ("1", "IN"),
                ("2", "IN"),
                ("3", "B_GATE"),
                ("4", "DRV"),
                ("5", "IN_SYS"),
                ("6", "UVLO"),
                ("7", "PLIM"),
                ("8", "GND"),
                ("9", "dVdT"),
                ("10", "ILIM"),
                ("11", "MODE"),
                ("12", "SHDN"),
            ],
            [
                ("13", "IMON"),
                ("14", "FLT"),
                ("15", "PGTH"),
                ("16", "PGOOD"),
                ("17", "OUT"),
                ("18", "OUT"),
                ("19", "NC"),
                ("20", "NC"),
                ("21", "NC"),
                ("22", "NC"),
                ("23", "NC"),
                ("24", "NC"),
                ("25", "PowerPAD"),
            ],
        ),
    ),
    "RPL_5_0": (
        "U",
        box_pins(
            [
                ("1", "PGND"),
                ("2", "PGND"),
                ("3", "PGND"),
                ("4", "PGND"),
                ("5", "PGND"),
                ("6", "VCC"),
                ("7", "SW"),
                ("8", "SW"),
                ("9", "VOUT"),
                ("10", "VOUT"),
                ("11", "VOUT"),
                ("12", "VOUT"),
            ],
            [
                ("13", "SW"),
                ("14", "SW"),
                ("15", "BST"),
                ("16", "CTRL"),
                ("17", "FB"),
                ("18", "AGND"),
                ("19", "SS"),
                ("20", "PG"),
                ("21", "PG"),
                ("22", "VIN"),
                ("23", "SW"),
                ("24", "PGND"),
            ],
        ),
    ),
    "CH32V307VCT6": (
        "U",
        [Pin(str(number), MCU_PIN_NAMES[number], "left" if number <= 50 else "right") for number in range(1, 101)],
    ),
    "ISO1042DW": (
        "U",
        box_pins(
            [
                ("1", "VCC1"),
                ("2", "GND1"),
                ("3", "TXD"),
                ("4", "NC"),
                ("5", "RXD"),
                ("6", "NC"),
                ("7", "NC"),
                ("8", "GND1"),
            ],
            [
                ("16", "VCC2"),
                ("15", "GND2"),
                ("14", "NC"),
                ("13", "CANH"),
                ("12", "CANL"),
                ("11", "VCC2"),
                ("10", "GND2"),
                ("9", "GND2"),
            ],
        ),
    ),
    "MEJ1S0305SC": ("U", box_pins([("1", "+VIN"), ("2", "-VIN")], [("7", "+VOUT"), ("5", "-VOUT")])),
    "CAN_CMC": ("L", box_pins([("1", "CANH_IN"), ("2", "CANL_IN")], [("4", "CANH_OUT"), ("3", "CANL_OUT")])),
    "CAN_TVS": ("D", box_pins([("1", "CANH"), ("2", "CANL")], [("3", "GND"), ("4", "GND")])),
    "TLP293_4": (
        "U",
        box_pins(
            [("1", "A1"), ("2", "K1"), ("3", "A2"), ("4", "K2"), ("5", "A3"), ("6", "K3"), ("7", "A4"), ("8", "K4")],
            [
                ("16", "C1"),
                ("15", "E1"),
                ("14", "C2"),
                ("13", "E2"),
                ("12", "C3"),
                ("11", "E3"),
                ("10", "C4"),
                ("9", "E4"),
            ],
        ),
    ),
    "SFM4_RELAY": (
        "K",
        box_pins(
            [("1", "COIL+"), ("2", "COIL-"), ("3", "SAFE_COM"), ("4", "SAFE_NO"), ("5", "SENSE_COM")],
            [("6", "SENSE_NO"), ("7", "HOLD_COM"), ("8", "HOLD_NO"), ("9", "EDM_COM"), ("10", "EDM_NC")],
        ),
    ),
    "TESTPOINT": ("TP", box_pins([("1", "TP")], [])),
}


def comp(
    reference: str,
    symbol: str,
    value: str,
    footprint: str,
    block: str,
    pins: dict[int | str, str | None],
    **kwargs: str | bool,
) -> Component:
    return Component(reference, symbol, value, footprint, block, {str(key): net for key, net in pins.items()}, **kwargs)


COMPONENTS: list[Component] = [
    comp(
        "J1",
        "CONN_4",
        "48V INPUT",
        "WB:MicroFit_2x2",
        "INPUT PROTECTION",
        {1: "VBAT_RAW", 2: "VBAT_RAW", 3: "GND_PWR", 4: "GND_PWR"},
        mpn="Molex 43045-0412",
    ),
    comp(
        "F1",
        "FUSE",
        "10A 125V",
        "WB:Fuse_4510",
        "INPUT PROTECTION",
        {1: "VBAT_RAW", 2: "VBAT_FUSED"},
        mpn="Littelfuse 0451010.MRL",
    ),
    comp(
        "D1",
        "DIODE",
        "SMCJ58A",
        "Diode_SMD:D_SMC",
        "INPUT PROTECTION",
        {1: "VBAT_FUSED", 2: "GND_PWR"},
        mpn="Littelfuse SMCJ58A",
    ),
    comp(
        "Q1",
        "NMOS",
        "150V N-MOS",
        "Package_SON:Infineon_PG-TDSON-8_6.15x5.15mm",
        "INPUT PROTECTION",
        {1: "FET_GATE", 2: "FET_COMMON", 3: "VBAT_FUSED"},
        mpn="Infineon BSC093N15NS5ATMA1",
    ),
    comp(
        "Q2",
        "NMOS",
        "150V N-MOS",
        "Package_SON:Infineon_PG-TDSON-8_6.15x5.15mm",
        "INPUT PROTECTION",
        {1: "FET_GATE", 2: "FET_COMMON", 3: "INPUT_SENSE"},
        mpn="Infineon BSC093N15NS5ATMA1",
    ),
    comp(
        "RS1",
        "RESISTOR",
        "6mR 3W 1%",
        "WB:Sense_3637",
        "INPUT PROTECTION",
        {1: "INPUT_SENSE", 2: "VBAT_PROTECTED"},
        mpn="Vishay WSL3637R0060FEA",
    ),
    comp(
        "U1",
        "LTC4368",
        "LTC4368HMS-2",
        "Package_SO:MSOP-10_3x3mm_P0.5mm",
        "INPUT PROTECTION",
        {
            1: "GND_PWR",
            2: "GND_PWR",
            3: "OV_SET",
            4: "UV_SET",
            5: "VBAT_FUSED",
            6: "U1_SHDN",
            7: None,
            8: "VBAT_PROTECTED",
            9: "INPUT_SENSE",
            10: "U1_GATE",
        },
        mpn="LTC4368HMS-2#PBF",
        datasheet="LTC4368 Rev C",
    ),
    comp("RG1", "RESISTOR", "22k", "Resistor_SMD:R_0603_1608Metric", "INPUT PROTECTION", {1: "U1_GATE", 2: "FET_GATE"}),
    comp(
        "CG1",
        "CAPACITOR",
        "4.7nF 100V",
        "Capacitor_SMD:C_0603_1608Metric",
        "INPUT PROTECTION",
        {1: "FET_GATE", 2: "FET_COMMON"},
    ),
    comp(
        "RUV1",
        "RESISTOR",
        "19.6M 1%",
        "Resistor_SMD:R_1206_3216Metric",
        "INPUT PROTECTION",
        {1: "VBAT_FUSED", 2: "UV_SET"},
    ),
    comp(
        "RUV2", "RESISTOR", "133k 1%", "Resistor_SMD:R_0603_1608Metric", "INPUT PROTECTION", {1: "UV_SET", 2: "OV_SET"}
    ),
    comp(
        "RUV3", "RESISTOR", "162k 1%", "Resistor_SMD:R_0603_1608Metric", "INPUT PROTECTION", {1: "OV_SET", 2: "GND_PWR"}
    ),
    comp(
        "RSH1",
        "RESISTOR",
        "510k",
        "Resistor_SMD:R_0603_1608Metric",
        "INPUT PROTECTION",
        {1: "VBAT_FUSED", 2: "U1_SHDN"},
    ),
    comp(
        "C1",
        "CAPACITOR",
        "1uF 100V",
        "Capacitor_SMD:C_1210_3225Metric",
        "INPUT PROTECTION",
        {1: "VBAT_PROTECTED", 2: "GND_PWR"},
    ),
    comp(
        "U2",
        "ISOLATED_DC_DC_TBD",
        "ISOLATED 48V-12V 240W (TBD)",
        "WB:Isolated_48V_12V_240W_TBD",
        "ISOLATED POWER",
        {1: "VBAT_PROTECTED", 2: "GND_PWR", 3: None, 4: "12V_ISO", 5: "GND", 6: None, 7: None, 8: None, 9: None},
        mpn="TBD_36_60V_TO_12V_240W_ISOLATED",
        dnp=True,
        note=(
            "No compatible orderable MPN is frozen; generic 9-pin through-hole land pattern is a layout "
            "placeholder only"
        ),
    ),
    comp(
        "C2",
        "CAPACITOR",
        "10uF 100V",
        "Capacitor_SMD:C_2220_5750Metric",
        "ISOLATED POWER",
        {1: "VBAT_PROTECTED", 2: "GND_PWR"},
    ),
    comp(
        "C3",
        "CAPACITOR",
        "470uF 25V",
        "Capacitor_THT:CP_Radial_D12.5mm_P5.00mm",
        "ISOLATED POWER",
        {1: "12V_ISO", 2: "GND"},
    ),
    comp(
        "J2",
        "CONN_4",
        "12V MOTOR AUX",
        "WB:MicroFit_2x2",
        "POWER OUTPUTS",
        {1: "12V_ISO", 2: "12V_ISO", 3: "GND", 4: "GND"},
        mpn="Molex 43045-0412",
    ),
    comp(
        "U3",
        "TPS26633RGE",
        "TPS26633RGE",
        "WB:TPS26633_RGE24",
        "JETSON EFUSE",
        {
            1: "12V_ISO",
            2: "12V_ISO",
            3: None,
            4: None,
            5: "12V_ISO",
            6: "U3_UVLO",
            7: "GND",
            8: "GND",
            9: "U3_DVDT",
            10: "U3_ILIM",
            11: None,
            12: "3V3_LOGIC",
            13: "U3_IMON",
            14: "JETSON_FAULT_N",
            15: "U3_PGTH",
            16: "JETSON_PGOOD",
            17: "JETSON_12V",
            18: "JETSON_12V",
            19: None,
            20: None,
            21: None,
            22: None,
            23: None,
            24: None,
            25: "GND",
        },
        mpn="Texas Instruments TPS26633RGER",
        datasheet="SLVSE94G",
    ),
    comp(
        "R59",
        "RESISTOR",
        "73.2k 1%",
        "Resistor_SMD:R_0603_1608Metric",
        "JETSON EFUSE",
        {1: "12V_ISO", 2: "U3_UVLO"},
    ),
    comp(
        "R60",
        "RESISTOR",
        "10.0k 1%",
        "Resistor_SMD:R_0603_1608Metric",
        "JETSON EFUSE",
        {1: "U3_UVLO", 2: "GND"},
    ),
    comp("R48", "RESISTOR", "3.00k 1%", "Resistor_SMD:R_0603_1608Metric", "JETSON EFUSE", {1: "U3_ILIM", 2: "GND"}),
    comp("C18", "CAPACITOR", "100nF", "Capacitor_SMD:C_0603_1608Metric", "JETSON EFUSE", {1: "U3_DVDT", 2: "GND"}),
    comp(
        "RPG1", "RESISTOR", "453k 1%", "Resistor_SMD:R_0603_1608Metric", "JETSON EFUSE", {1: "JETSON_12V", 2: "U3_PGTH"}
    ),
    comp("RPG2", "RESISTOR", "56.0k 1%", "Resistor_SMD:R_0603_1608Metric", "JETSON EFUSE", {1: "U3_PGTH", 2: "GND"}),
    comp(
        "RPG3", "RESISTOR", "10k", "Resistor_SMD:R_0603_1608Metric", "JETSON EFUSE", {1: "3V3_LOGIC", 2: "JETSON_PGOOD"}
    ),
    comp(
        "R47",
        "RESISTOR",
        "10k",
        "Resistor_SMD:R_0603_1608Metric",
        "JETSON EFUSE",
        {1: "3V3_LOGIC", 2: "JETSON_FAULT_N"},
    ),
    comp("R51", "RESISTOR", "10k", "Resistor_SMD:R_0603_1608Metric", "JETSON EFUSE", {1: "U3_IMON", 2: "GND"}),
    comp("C4", "CAPACITOR", "1uF 25V", "Capacitor_SMD:C_0805_2012Metric", "JETSON EFUSE", {1: "12V_ISO", 2: "GND"}),
    comp(
        "C5",
        "CAPACITOR",
        "220uF 25V",
        "Capacitor_THT:CP_Radial_D10.0mm_P5.00mm",
        "JETSON EFUSE",
        {1: "JETSON_12V", 2: "GND"},
    ),
    comp(
        "J3",
        "CONN_4",
        "JETSON DEVKIT 12V",
        "WB:MicroFit_2x2",
        "JETSON EFUSE",
        {1: "JETSON_12V", 2: "JETSON_12V", 3: "GND", 4: "GND"},
        mpn="Molex 43045-0412",
    ),
    comp(
        "U4",
        "RPL_5_0",
        "RPL-5.0 3V3/5A",
        "WB:RPL-5.0_QFN24",
        "3V3 POWER",
        {
            **{index: "GND" for index in [1, 2, 3, 4, 5, 24]},
            6: "U4_VCC",
            7: None,
            8: None,
            9: "3V3_LOGIC",
            10: "3V3_LOGIC",
            11: "3V3_LOGIC",
            12: "3V3_LOGIC",
            13: None,
            14: None,
            15: None,
            16: "U4_CTRL",
            17: "U4_FB",
            18: "GND",
            19: "U4_SS",
            20: "3V3_PGOOD",
            21: "3V3_PGOOD",
            22: "12V_ISO",
            23: None,
        },
        mpn="RECOM RPL-5.0-R",
        datasheet="RPL-5.0 Rev 2-2025",
    ),
    comp("RFB1", "RESISTOR", "45.0k 1%", "Resistor_SMD:R_0603_1608Metric", "3V3 POWER", {1: "3V3_LOGIC", 2: "U4_FB"}),
    comp("RFB2", "RESISTOR", "10.0k 1%", "Resistor_SMD:R_0603_1608Metric", "3V3 POWER", {1: "U4_FB", 2: "GND"}),
    comp("R46", "RESISTOR", "100k", "Resistor_SMD:R_0603_1608Metric", "3V3 POWER", {1: "12V_ISO", 2: "U4_CTRL"}),
    comp("CSS4", "CAPACITOR", "22nF", "Capacitor_SMD:C_0603_1608Metric", "3V3 POWER", {1: "U4_SS", 2: "GND"}),
    comp("C20", "CAPACITOR", "1uF 10V", "Capacitor_SMD:C_0603_1608Metric", "3V3 POWER", {1: "U4_VCC", 2: "GND"}),
    comp("C6", "CAPACITOR", "22uF 25V", "Capacitor_SMD:C_1210_3225Metric", "3V3 POWER", {1: "12V_ISO", 2: "GND"}),
    comp("C7", "CAPACITOR", "47uF 10V", "Capacitor_SMD:C_1210_3225Metric", "3V3 POWER", {1: "3V3_LOGIC", 2: "GND"}),
    comp("C8", "CAPACITOR", "47uF 10V", "Capacitor_SMD:C_1210_3225Metric", "3V3 POWER", {1: "3V3_LOGIC", 2: "GND"}),
]


MCU_NETS: dict[int, str | None] = {number: None for number in range(1, 101)}
for number in [6, 11, 21, 22, 28, 50, 75, 100]:
    MCU_NETS[number] = "3V3_LOGIC"
for number in [10, 19, 20, 27, 49, 74, 99]:
    MCU_NETS[number] = "GND"
MCU_NETS.update(
    {
        12: "OSC_IN",
        13: "OSC_OUT",
        14: "MCU_RESET",
        30: "SPI_SCLK_MCU",
        31: "SPI_MISO_MCU",
        32: "SPI_MOSI_MCU",
        35: "MOTOR_CS0_MCU",
        36: "MOTOR_CS1_MCU",
        47: "MOTOR_CS2_MCU",
        48: "MOTOR_CS3_MCU",
        51: "MOTOR_CS4_MCU",
        52: "MOTOR_CS5_MCU",
        53: "MOTOR_ENABLE_REQ",
        54: "ESTOP_SENSE",
        55: "RELAY_A_NC",
        56: "RELAY_B_NC",
        57: "ESTOP_A_MON",
        58: "ESTOP_B_MON",
        68: "UART_TX_MCU",
        69: "UART_RX_MCU",
        72: "SWDIO",
        76: "SWCLK",
        81: "CAN_RX",
        82: "CAN_TX",
        91: "JETSON_ENABLE_REQ",
        92: "I2C_SCL_MCU",
        93: "I2C_SDA_MCU",
        94: "BOOT0",
    }
)


COMPONENTS.extend(
    [
        comp(
            "U5",
            "CH32V307VCT6",
            "CH32V307VCT6",
            "Package_QFP:LQFP-100_14x14mm_P0.5mm",
            "MCU AND BACKPLANE",
            MCU_NETS,
            mpn="WCH CH32V307VCT6",
        ),
        comp(
            "Y1",
            "CRYSTAL",
            "8MHz",
            "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm",
            "MCU AND BACKPLANE",
            {1: "OSC_IN", 2: "OSC_OUT"},
            mpn="Abracon ABM8-8.000MHZ-B2-T",
        ),
        comp(
            "CY1", "CAPACITOR", "18pF", "Capacitor_SMD:C_0603_1608Metric", "MCU AND BACKPLANE", {1: "OSC_IN", 2: "GND"}
        ),
        comp(
            "CY2", "CAPACITOR", "18pF", "Capacitor_SMD:C_0603_1608Metric", "MCU AND BACKPLANE", {1: "OSC_OUT", 2: "GND"}
        ),
        comp(
            "R54",
            "RESISTOR",
            "10k",
            "Resistor_SMD:R_0603_1608Metric",
            "MCU AND BACKPLANE",
            {1: "3V3_LOGIC", 2: "MCU_RESET"},
        ),
        comp(
            "C19",
            "CAPACITOR",
            "100nF",
            "Capacitor_SMD:C_0603_1608Metric",
            "MCU AND BACKPLANE",
            {1: "MCU_RESET", 2: "GND"},
        ),
        comp("R43", "RESISTOR", "100k", "Resistor_SMD:R_0603_1608Metric", "MCU AND BACKPLANE", {1: "BOOT0", 2: "GND"}),
        comp(
            "J13",
            "CONN_4",
            "WCH DEBUG",
            "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical",
            "MCU AND BACKPLANE",
            {1: "3V3_LOGIC", 2: "SWDIO", 3: "SWCLK", 4: "GND"},
        ),
        comp(
            "J4",
            "CONN_20",
            "JETSON MCU BACKPLANE",
            "Connector_PinHeader_2.54mm:PinHeader_2x10_P2.54mm_Vertical",
            "MCU AND BACKPLANE",
            {
                1: "3V3_LOGIC",
                2: "GND",
                3: "3V3_LOGIC",
                4: "GND",
                5: "SPI_SCLK",
                6: "SPI_MOSI",
                7: "SPI_MISO",
                8: "JETSON_ENABLE_REQ",
                9: "MOTOR_CS0",
                10: "MOTOR_CS1",
                11: "MOTOR_CS2",
                12: "MOTOR_CS3",
                13: "MOTOR_CS4",
                14: "MOTOR_CS5",
                15: "I2C_SDA",
                16: "I2C_SCL",
                17: "ESTOP_SENSE",
                18: "UART_TX",
                19: "UART_RX",
                20: "MCU_RESET",
            },
        ),
    ]
)


SERIES_SIGNALS = [
    ("SPI_SCLK_MCU", "SPI_SCLK"),
    ("SPI_MOSI_MCU", "SPI_MOSI"),
    ("SPI_MISO_MCU", "SPI_MISO"),
    ("MOTOR_CS0_MCU", "MOTOR_CS0"),
    ("MOTOR_CS1_MCU", "MOTOR_CS1"),
    ("MOTOR_CS2_MCU", "MOTOR_CS2"),
    ("MOTOR_CS3_MCU", "MOTOR_CS3"),
    ("MOTOR_CS4_MCU", "MOTOR_CS4"),
    ("MOTOR_CS5_MCU", "MOTOR_CS5"),
    ("I2C_SCL_MCU", "I2C_SCL"),
    ("I2C_SDA_MCU", "I2C_SDA"),
    ("UART_TX_MCU", "UART_TX"),
    ("UART_RX_MCU", "UART_RX"),
]
for index, (source, target) in enumerate(SERIES_SIGNALS, start=30):
    COMPONENTS.append(
        comp(
            f"R{index}",
            "RESISTOR",
            "33R",
            "Resistor_SMD:R_0603_1608Metric",
            "MCU AND BACKPLANE",
            {1: source, 2: target},
        )
    )
COMPONENTS.extend(
    [
        comp(
            "R56",
            "RESISTOR",
            "4.7k",
            "Resistor_SMD:R_0603_1608Metric",
            "MCU AND BACKPLANE",
            {1: "3V3_LOGIC", 2: "I2C_SDA"},
        ),
        comp(
            "R55",
            "RESISTOR",
            "4.7k",
            "Resistor_SMD:R_0603_1608Metric",
            "MCU AND BACKPLANE",
            {1: "3V3_LOGIC", 2: "I2C_SCL"},
        ),
    ]
)
for index in range(9, 17):
    COMPONENTS.append(
        comp(
            f"C{index}",
            "CAPACITOR",
            "100nF",
            "Capacitor_SMD:C_0603_1608Metric",
            "MCU AND BACKPLANE",
            {1: "3V3_LOGIC", 2: "GND"},
        )
    )
COMPONENTS.append(
    comp(
        "C17", "CAPACITOR", "4.7uF", "Capacitor_SMD:C_0805_2012Metric", "MCU AND BACKPLANE", {1: "3V3_LOGIC", 2: "GND"}
    )
)


COMPONENTS.extend(
    [
        comp(
            "U6",
            "ISO1042DW",
            "ISO1042DW",
            "WB:ISO1042_DW16_HV",
            "ISOLATED CAN FD",
            {
                1: "3V3_LOGIC",
                2: "GND",
                3: "CAN_TX",
                4: None,
                5: "CAN_RX",
                6: None,
                7: None,
                8: "GND",
                9: "GND_CAN_ISO",
                10: "GND_CAN_ISO",
                11: "5V_CAN_ISO",
                12: "CANL_RAW",
                13: "CANH_RAW",
                14: None,
                15: "GND_CAN_ISO",
                16: "5V_CAN_ISO",
            },
            mpn="Texas Instruments ISO1042DWR",
            datasheet="SLLSF09F",
        ),
        comp(
            "U7",
            "MEJ1S0305SC",
            "3V3-5V ISO 1W",
            "Converter_DCDC:Converter_DCDC_muRata_MEJ1SxxxxSC_THT",
            "ISOLATED CAN FD",
            {1: "3V3_LOGIC", 2: "GND", 5: "GND_CAN_ISO", 7: "5V_CAN_ISO"},
            mpn="Murata MEJ1S0305SC",
        ),
        comp(
            "C40",
            "CAPACITOR",
            "100nF",
            "Capacitor_SMD:C_0603_1608Metric",
            "ISOLATED CAN FD",
            {1: "3V3_LOGIC", 2: "GND"},
        ),
        comp(
            "C41",
            "CAPACITOR",
            "100nF",
            "Capacitor_SMD:C_0603_1608Metric",
            "ISOLATED CAN FD",
            {1: "5V_CAN_ISO", 2: "GND_CAN_ISO"},
        ),
        comp(
            "C44",
            "CAPACITOR",
            "100nF",
            "Capacitor_SMD:C_0603_1608Metric",
            "ISOLATED CAN FD",
            {1: "5V_CAN_ISO", 2: "GND_CAN_ISO"},
        ),
        comp(
            "C42",
            "CAPACITOR",
            "4.7uF",
            "Capacitor_SMD:C_0805_2012Metric",
            "ISOLATED CAN FD",
            {1: "3V3_LOGIC", 2: "GND"},
        ),
        comp(
            "C43",
            "CAPACITOR",
            "4.7uF",
            "Capacitor_SMD:C_0805_2012Metric",
            "ISOLATED CAN FD",
            {1: "5V_CAN_ISO", 2: "GND_CAN_ISO"},
        ),
        comp(
            "L1",
            "CAN_CMC",
            "100R@100MHz",
            "WB:ACT45B",
            "ISOLATED CAN FD",
            {1: "CANH_RAW", 2: "CANL_RAW", 3: "CANL", 4: "CANH"},
            mpn="TDK ACT45B-101-2P-TL003",
        ),
        comp(
            "D2",
            "CAN_TVS",
            "CAN FD TVS",
            "WB:CAN_TVS",
            "ISOLATED CAN FD",
            {1: "CANH", 2: "CANL", 3: "GND_CAN_ISO", 4: "GND_CAN_ISO"},
            mpn="Nexperia PESD2CANFD24V-T",
        ),
        comp(
            "R58",
            "RESISTOR",
            "120R 1%",
            "Resistor_SMD:R_1206_3216Metric",
            "ISOLATED CAN FD",
            {1: "CANH", 2: "CAN_TERM"},
        ),
        comp(
            "JP1",
            "CONN_2",
            "CAN TERM",
            "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
            "ISOLATED CAN FD",
            {1: "CAN_TERM", 2: "CANL"},
        ),
        comp(
            "J5",
            "CONN_4",
            "CAN A",
            "WB:MicroFit_2x2",
            "ISOLATED CAN FD",
            {1: "CANH", 2: "CANL", 3: "GND_CAN_ISO", 4: None},
            mpn="Molex 43045-0412",
        ),
        comp(
            "J6",
            "CONN_4",
            "CAN B",
            "WB:MicroFit_2x2",
            "ISOLATED CAN FD",
            {1: "CANH", 2: "CANL", 3: "GND_CAN_ISO", 4: None},
            mpn="Molex 43045-0412",
        ),
    ]
)


COMPONENTS.extend(
    [
        comp(
            "F2",
            "FUSE",
            "PTC 0.25A",
            "Fuse:Fuse_1206_3216Metric",
            "HARDWIRED ESTOP",
            {1: "12V_ISO", 2: "ESTOP_12V"},
            mpn="Littelfuse 1206L025YR",
        ),
        comp(
            "J10",
            "CONN_4",
            "DUAL ESTOP LOOP",
            "WB:MicroFit_2x2",
            "HARDWIRED ESTOP",
            {1: "ESTOP_12V", 2: "ESTOP_CH_A_RETURN", 3: "ESTOP_12V", 4: "ESTOP_CH_B_RETURN"},
            mpn="Molex 43045-0412",
        ),
        comp(
            "J12",
            "CONN_4",
            "DUAL MANUAL RESET",
            "WB:MicroFit_2x2",
            "HARDWIRED ESTOP",
            {1: "ESTOP_CH_A_RETURN", 2: "RESET_CH_A_RETURN", 3: "ESTOP_CH_B_RETURN", 4: "RESET_CH_B_RETURN"},
            mpn="Molex 43045-0412",
        ),
        comp(
            "K1",
            "SFM4_RELAY",
            "FORCE-GUIDED 12V A",
            "WB:Panasonic_SFM4",
            "HARDWIRED ESTOP",
            {
                1: "RESET_CH_A_RETURN",
                2: "GND",
                3: "MOTOR_ENABLE_REQ",
                4: "SAFE_STAGE_A",
                5: "3V3_LOGIC",
                6: "SENSE_STAGE_A",
                7: "ESTOP_CH_A_RETURN",
                8: "RESET_CH_A_RETURN",
                9: "3V3_LOGIC",
                10: "RELAY_A_NC",
            },
            mpn="Panasonic SFM4-DC12V",
            note="Safety review and relay contact mapping confirmation required",
        ),
        comp(
            "K2",
            "SFM4_RELAY",
            "FORCE-GUIDED 12V B",
            "WB:Panasonic_SFM4",
            "HARDWIRED ESTOP",
            {
                1: "RESET_CH_B_RETURN",
                2: "GND",
                3: "SAFE_STAGE_A",
                4: "MOTOR_ENABLE_SAFE",
                5: "SENSE_STAGE_A",
                6: "ESTOP_SENSE",
                7: "ESTOP_CH_B_RETURN",
                8: "RESET_CH_B_RETURN",
                9: "3V3_LOGIC",
                10: "RELAY_B_NC",
            },
            mpn="Panasonic SFM4-DC12V",
            note="Safety review and relay contact mapping confirmation required",
        ),
        comp(
            "D3",
            "DIODE",
            "FLYBACK",
            "Diode_SMD:D_SOD-123",
            "HARDWIRED ESTOP",
            {1: "RESET_CH_A_RETURN", 2: "GND"},
            mpn="Diodes Inc. 1N4148W-7-F",
        ),
        comp(
            "D4",
            "DIODE",
            "FLYBACK",
            "Diode_SMD:D_SOD-123",
            "HARDWIRED ESTOP",
            {1: "RESET_CH_B_RETURN", 2: "GND"},
            mpn="Diodes Inc. 1N4148W-7-F",
        ),
        comp(
            "R57", "RESISTOR", "100k", "Resistor_SMD:R_0603_1608Metric", "HARDWIRED ESTOP", {1: "ESTOP_SENSE", 2: "GND"}
        ),
        comp(
            "R44", "RESISTOR", "100k", "Resistor_SMD:R_0603_1608Metric", "HARDWIRED ESTOP", {1: "RELAY_A_NC", 2: "GND"}
        ),
        comp(
            "R45", "RESISTOR", "100k", "Resistor_SMD:R_0603_1608Metric", "HARDWIRED ESTOP", {1: "RELAY_B_NC", 2: "GND"}
        ),
        comp(
            "U8",
            "TLP293_4",
            "ESTOP DIAGNOSTIC OPTO",
            "Package_SO:SOIC-16W_7.5x10.3mm_P1.27mm",
            "HARDWIRED ESTOP",
            {
                1: "ESTOP_CH_A_RETURN",
                2: "U8_LED_A_K",
                3: "ESTOP_CH_B_RETURN",
                4: "U8_LED_B_K",
                5: None,
                6: None,
                7: None,
                8: None,
                9: None,
                10: None,
                11: None,
                12: None,
                13: "GND",
                14: "ESTOP_B_MON",
                15: "GND",
                16: "ESTOP_A_MON",
            },
            mpn="Toshiba TLP293-4(GB,E)",
        ),
        comp(
            "R52", "RESISTOR", "4.7k", "Resistor_SMD:R_0603_1608Metric", "HARDWIRED ESTOP", {1: "U8_LED_A_K", 2: "GND"}
        ),
        comp(
            "R53", "RESISTOR", "4.7k", "Resistor_SMD:R_0603_1608Metric", "HARDWIRED ESTOP", {1: "U8_LED_B_K", 2: "GND"}
        ),
        comp(
            "R49",
            "RESISTOR",
            "10k",
            "Resistor_SMD:R_0603_1608Metric",
            "HARDWIRED ESTOP",
            {1: "3V3_LOGIC", 2: "ESTOP_A_MON"},
        ),
        comp(
            "R50",
            "RESISTOR",
            "10k",
            "Resistor_SMD:R_0603_1608Metric",
            "HARDWIRED ESTOP",
            {1: "3V3_LOGIC", 2: "ESTOP_B_MON"},
        ),
        comp(
            "J11",
            "CONN_4",
            "SAFETY OUTPUT",
            "WB:MicroFit_2x2",
            "HARDWIRED ESTOP",
            {1: "MOTOR_ENABLE_SAFE", 2: "ESTOP_SENSE", 3: "GND", 4: "3V3_LOGIC"},
            mpn="Molex 43045-0412",
        ),
    ]
)


for reference, net in [
    ("TP1", "VBAT_PROTECTED"),
    ("TP2", "12V_ISO"),
    ("TP3", "JETSON_12V"),
    ("TP4", "3V3_LOGIC"),
    ("TP5", "GND"),
    ("TP6", "CANH"),
    ("TP7", "CANL"),
    ("TP8", "MCU_RESET"),
]:
    COMPONENTS.append(comp(reference, "TESTPOINT", net, "TestPoint:TestPoint_Pad_D1.5mm", "TEST ACCESS", {1: net}))


BLOCK_ORDER = [
    "INPUT PROTECTION",
    "ISOLATED POWER",
    "JETSON EFUSE",
    "3V3 POWER",
    "POWER OUTPUTS",
    "MCU AND BACKPLANE",
    "ISOLATED CAN FD",
    "HARDWIRED ESTOP",
    "TEST ACCESS",
]


CRITICAL_MPNS = {
    component.reference: component.mpn
    for component in COMPONENTS
    if component.reference
    in {
        "J1",
        "F1",
        "U1",
        "U2",
        "U3",
        "U4",
        "U5",
        "U6",
        "U7",
        "U8",
        "J2",
        "J3",
        "J5",
        "J6",
        "J10",
        "J11",
        "J12",
        "K1",
        "K2",
    }
}
