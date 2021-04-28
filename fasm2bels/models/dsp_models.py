#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Copyright (C) 2021  The SymbiFlow Authors.
#
# Use of this source code is governed by a ISC-style
# license that can be found in the LICENSE file or at
# https://opensource.org/licenses/ISC
#
# SPDX-License-Identifier: ISC

from .verilog_modeling import Bel, Site, make_inverter_path
import math


def make_hex_verilog_value(width, value):
    return "{width}'h{{:0{format_width}X}}".format(
        width=width, format_width=int(math.ceil(width / 4))).format(value)


def get_dsp_site(db, grid, tile, attribute):
    """ Return the prjxray.tile.Site object for the given DSP site. """
    gridinfo = grid.gridinfo_at_tilename(tile)
    tile_type = db.get_tile_type(gridinfo.tile_type)
    

    target_type = 'DSP48E1'
    sites = tile_type.get_instance_sites(gridinfo)
    for site in sites:
        for pin in site.site_pins:
            if site.type == target_type and pin.wire == attribute:
                print(f"returning {site} from pin {pin}")
                return site

    assert False, sites

def process_dsp_slice(top, features, set_features):
    aparts = features[0].feature.split('.')
    dsp_site = get_dsp_site(top.db, top.grid, aparts[0], aparts[1])
    site = Site(features, dsp_site)

    bel = Bel('DSP48E1')
    bel.set_bel('DSP48E1')
    site.add_bel(bel, name='DSP48E1')
    site.override_site_type('DSP48E1')
    
    dsp_site = dsp_site.type == 'DSP48E1'

    dsp_site_wire_map = {
        'RSTA': 'RSTA',
        'RSTALLCARRYIN': 'RSTALLCARRYIN',
        'RSTALUMODE': 'RSTALUMODE',
        'RSTB': 'RSTB',
        'RSTC': 'RSTC',
        'RSTCTRL': 'RSTCTRL',
        'RSTD': 'RSTD',
        'RSTINMODE': 'RSTINMODE',
        'RSTM': 'RSTM',
        'RSTP': 'RSTP',
    }
    
    def make_wire(wire_name):
        if dsp_site and wire_name in dsp_site_wire_map:
            return dsp_site_wire_map[wire_name]
        else:
            return wire_name

    def make_target_feature(feature):
        return '{}.{}.{}'.format(aparts[0], aparts[1], feature)
    
    '''
    # parameters
    AREG = 1
    if 'AREG_0' in set_features:
        AREG = 0
    elif 'AREG_1' in set_features:
        AREG = 1
    elif 'AREG_2' in set_features:
        AREG = 2
    elif fnmatch.fnmatch(set_features, 'AREG_[3-9]'):
        assert False, "Invalid AREG parameter. Must be 0, 1, 2"
    
    bel.parameters['AREG'] = AREG
    
    ACASCREG = 1
    if AREG == 0:
        ACASCREG = 0
    elif AREG == 1:
        ACASCREG = 1
    bel.parameters['ACASCREG'] = ACASCREG

    BREG = 1
    if 'BREG_0' in set_features:
        BREG = 0
    elif 'BREG_1' in set_features:
        BREG = 1
    elif 'BREG_2' in set_features:
        BREG = 2
    elif fnmatch.fnmatch(set_features, 'BREG_[3-9]'):
        assert False, "Invalid BREG parameter. Must be 0, 1, 2"
    bel.parameters['BREG'] = BREG
    
    BCASCREG = 1
    if BREG == 0:
        BCASCREG = 0
    elif BREG == 1:
        BCASCREG = 1
    bel.parameters['BCASCREG'] = BCASCREG
    
    A_INPUT = 'DIRECT' # default 
    B_INPUT = 'DIRECT'
    bel.parameters['A_INPUT'] = A_INPUT
    bel.parameters['B_INPUT'] = B_INPUT
    '''

    parameter_binds = [
        ('ADREG', 'ZADREG', True, 1),
        ('ALUMODEREG', 'ZALUMODEREG', True, 1),
        ('CARRYINREG', 'ZCARRYINREG', True, 1),
        ('CARRYINSELREG', 'ZCARRYINSELREG', True, 1),
    ]
    
    for vparam, fparam, invert, width in parameter_binds:
        bel.parameters[vparam] = get_init(
            features, [make_target_feature(p) for p in fparam],
            invert=invert,
            width=width)

    # Reset input signals
    for wire in (
        'RSTA',
        'RSTB',
        'RSTC',
        'RSTD',
        'RSTCTRL',
        'RSTALUMODE',
        'RSTINMODE',
        'RSTM',
        'RSTP',
    ):
        wire_inverted = (not 'ZINV_{}'.format(wire) in set_features)
        site_pips = make_inverter_path(wire, wire_inverted)

        wire_name = make_wire(wire)
        site.add_sink(
            bel=bel,
            cell_pin=wire,
            sink_site_pin=wire_name,
            bel_name=bel.bel,
            bel_pin=wire,
            site_pips=site_pips,
            sink_site_type_pin=wire,
        )

    # clock enable signals
    for wire in (
        'CEAD',
        'CEALUMODE',
        'CEA1',
        'CEA2',
        'CEB1',
        'CEB2',
        'CEC',
        'CECARRYIN',
        'CECTRL',
        'CED',
        'CEINMODE',
        'CEM',
        'CEP',
    ):
        wire_inverted = (not 'ZINV_{}'.format(wire) in set_features)
        site_pips = make_inverter_path(wire, wire_inverted)

        wire_name = make_wire(wire)
        site.add_sink(
            bel=bel,
            cell_pin=wire,
            sink_site_pin=wire_name,
            bel_name=bel.bel,
            bel_pin=wire,
            site_pips=site_pips,
            sink_site_type_pin=wire,
        )

    input_wires = [
        #("ACIN", 30),
        ("ALUMODE", 4),
        ("A", 30),
        #("BCIN", 18),
        ("B", 18),
        ("CARRYINSEL", 3),
        #("C", 48),
        ("D", 25),
        ("INMODE", 5),
        ("OPMODE", 7),
        #("PCIN", 48),
    ]

    for input_wire, width in input_wires:
        for idx in range(width):
            site_wire = '{}{}'.format(input_wire, idx)
            wire_name = make_wire(site_wire)
            site.add_sink(
                bel=bel,
                cell_pin='{}[{}]'.format(input_wire, idx),
                sink_site_pin=wire_name,
                bel_name=bel.bel,
                bel_pin=site_wire,
                sink_site_type_pin=site_wire)

    for output_wire, width in [
        ('ACOUT', 30),
        ('BCOUT', 18),
        ('CARRYOUT', 4),
        #('PCOUT', 48),
        ('P', 48),
    ]:
        for idx in range(width):
            input_wire = '{}{}'.format(output_wire, idx)
            wire_name = make_wire(input_wire)
            pin_name = '{}[{}]'.format(output_wire, idx)
            site.add_source(
                bel=bel,
                cell_pin=pin_name,
                source_site_pin=wire_name,
                bel_name=bel.bel,
                bel_pin=input_wire,
                source_site_type_pin=input_wire)

    top.add_site(site)

    return site


def process_dsp(conn, top, tile_name, features):
    tile_features = set()
    dsps = {'DSP_0': [], 'DSP_1': []} 
    dsp_features = {'DSP_0': set(), 'DSP_1': set()} 
    for f in features:
        if f.value == 0:
            continue

        parts = f.feature.split('.')
        
        tile_features.add('.'.join(parts[1:]))
        if  'DSP_0_' in parts[1]:
            dsp_features['DSP_0'].add('.'.join(parts[1:]))
            dsps['DSP_0'].append(f)
        elif 'DSP_1_' in parts[1]:
            dsp_features['DSP_1'].add('.'.join(parts[1:]))
            dsps['DSP_1'].append(f)
        #elif parts[2] in dsps:
        #    dsp_features[parts[2]].add('.'.join(parts[3:]))
        #    dsps[parts[2]].append(f)
    
    print(f"dsps = {dsps}")
    print(f"features = {dsp_features}")

    """
    DSP48E1 Config:

    DSP_[01]_CEAD.DSP_GND_L 26_63
    DSP_[01]_CEAD.DSP_VCC_L 27_62
    DSP_[01]_CEALUMODE.DSP_GND_L 27_51
    DSP_[01]_CEALUMODE.DSP_VCC_L 26_50
    DSP_[01]_CED.DSP_GND_L 27_72
    DSP_[01]_CED.DSP_VCC_L 26_72
    DSP_[01]_CEINMODE.DSP_GND_L 26_69
    DSP_[01]_CEINMODE.DSP_VCC_L 26_67
    DSP_[01]_RSTD.DSP_GND_L 27_96
    DSP_[01]_RSTD.DSP_VCC_L 27_85
    DSP_[01]_ALUMODE2.DSP_GND_L 27_56
    DSP_[01]_ALUMODE2.DSP_VCC_L 26_55
    DSP_[01]_ALUMODE3.DSP_GND_L 27_60
    DSP_[01]_ALUMODE3.DSP_VCC_L 26_53
    DSP_[01]_CARRYINSEL2.DSP_GND_L 26_17
    DSP_[01]_CARRYINSEL2.DSP_VCC_L 27_18
    DSP_[01]_D0.DSP_GND_L 26_65
    DSP_[01]_D0.DSP_VCC_L 27_64
    DSP_[01]_D1.DSP_GND_L 27_68
    DSP_[01]_D1.DSP_VCC_L 27_74
    DSP_[01]_D2.DSP_GND_L 27_71
    DSP_[01]_D2.DSP_VCC_L 27_70
    DSP_[01]_D3.DSP_GND_L 26_75
    DSP_[01]_D3.DSP_VCC_L 26_73
    DSP_[01]_D4.DSP_GND_L 27_78
    DSP_[01]_D4.DSP_VCC_L 26_77
    DSP_[01]_D5.DSP_GND_L 26_82
    DSP_[01]_D5.DSP_VCC_L 26_81
    DSP_[01]_D6.DSP_GND_L 26_89
    DSP_[01]_D6.DSP_VCC_L 27_89
    DSP_[01]_D7.DSP_GND_L 27_91
    DSP_[01]_D7.DSP_VCC_L 26_91
    DSP_[01]_D8.DSP_GND_L 26_98
    DSP_[01]_D8.DSP_VCC_L 27_97
    DSP_[01]_D9.DSP_GND_L 26_101
    DSP_[01]_D9.DSP_VCC_L 26_99
    DSP_[01]_D10.DSP_GND_L 26_105
    DSP_[01]_D10.DSP_VCC_L 26_103
    DSP_[01]_D11.DSP_GND_L 27_107
    DSP_[01]_D11.DSP_VCC_L 27_105
    DSP_[01]_D12.DSP_GND_L 26_107
    DSP_[01]_D12.DSP_VCC_L 26_111
    DSP_[01]_D13.DSP_GND_L 27_113
    DSP_[01]_D13.DSP_VCC_L 26_114
    DSP_[01]_D14.DSP_GND_L 26_118
    DSP_[01]_D14.DSP_VCC_L 27_116
    DSP_[01]_D15.DSP_GND_L 27_122
    DSP_[01]_D15.DSP_VCC_L 27_120
    DSP_[01]_D16.DSP_GND_L 27_125
    DSP_[01]_D16.DSP_VCC_L 26_125
    DSP_[01]_D17.DSP_GND_L 27_128
    DSP_[01]_D17.DSP_VCC_L 27_126
    DSP_[01]_D18.DSP_GND_L 26_135
    DSP_[01]_D18.DSP_VCC_L 26_131
    DSP_[01]_D19.DSP_GND_L 27_140
    DSP_[01]_D19.DSP_VCC_L 26_140
    DSP_[01]_D20.DSP_GND_L 26_145
    DSP_[01]_D20.DSP_VCC_L 27_143
    DSP_[01]_D21.DSP_GND_L 27_147
    DSP_[01]_D21.DSP_VCC_L 26_147
    DSP_[01]_D22.DSP_GND_L 27_151
    DSP_[01]_D22.DSP_VCC_L 26_150
    DSP_[01]_D23.DSP_GND_L 27_154
    DSP_[01]_D23.DSP_VCC_L 27_153
    DSP_[01]_D24.DSP_GND_L 27_158
    DSP_[01]_D24.DSP_VCC_L 27_155
    DSP_[01]_INMODE0.DSP_GND_L 27_134
    DSP_[01]_INMODE0.DSP_VCC_L 27_130
    DSP_[01]_INMODE1.DSP_GND_L 26_133
    DSP_[01]_INMODE1.DSP_VCC_L 27_145
    DSP_[01]_INMODE2.DSP_GND_L 27_80
    DSP_[01]_INMODE2.DSP_VCC_L 26_71
    DSP_[01]_INMODE3.DSP_GND_L 27_79
    DSP_[01]_INMODE3.DSP_VCC_L 26_70
    DSP_[01]_INMODE4.DSP_GND_L 26_58
    DSP_[01]_INMODE4.DSP_VCC_L 26_46
    DSP_[01]_OPMODE6.DSP_GND_L 27_12
    DSP_[01]_OPMODE6.DSP_VCC_L 27_20

    DSP48.DSP_[01].A_INPUT[0] 27_84
    DSP48.DSP_[01].AREG_0 26_113 26_137 27_111
    DSP48.DSP_[01].AREG_2 27_136
    DSP48.DSP_[01].AUTORESET_PATDET_RESET 26_79
    DSP48.DSP_[01].AUTORESET_PATDET_RESET_NOT_MATCH 26_78
    DSP48.DSP_[01].B_INPUT[0] 26_11
    DSP48.DSP_[01].BREG_0 26_40 26_48 27_38
    DSP48.DSP_[01].BREG_2 27_47
    DSP48.DSP_[01].MASK[0] 27_01
    DSP48.DSP_[01].MASK[1] 26_03
    DSP48.DSP_[01].MASK[2] 27_06
    DSP48.DSP_[01].MASK[3] 26_07
    DSP48.DSP_[01].MASK[4] 26_10
    DSP48.DSP_[01].MASK[5] 27_11
    DSP48.DSP_[01].MASK[6] 26_18
    DSP48.DSP_[01].MASK[7] 27_19
    DSP48.DSP_[01].MASK[8] 26_22
    DSP48.DSP_[01].MASK[9] 27_23
    DSP48.DSP_[01].MASK[10] 27_26
    DSP48.DSP_[01].MASK[11] 26_28
    DSP48.DSP_[01].MASK[12] 26_41
    DSP48.DSP_[01].MASK[13] 27_42
    DSP48.DSP_[01].MASK[14] 26_45
    DSP48.DSP_[01].MASK[15] 27_46
    DSP48.DSP_[01].MASK[16] 26_49
    DSP48.DSP_[01].MASK[17] 27_50
    DSP48.DSP_[01].MASK[18] 27_57
    DSP48.DSP_[01].MASK[19] 26_59
    DSP48.DSP_[01].MASK[20] 26_62
    DSP48.DSP_[01].MASK[21] 27_63
    DSP48.DSP_[01].MASK[22] 26_66
    DSP48.DSP_[01].MASK[23] 27_67
    DSP48.DSP_[01].MASK[24] 27_86
    DSP48.DSP_[01].MASK[25] 26_88
    DSP48.DSP_[01].MASK[26] 27_90
    DSP48.DSP_[01].MASK[27] 26_92
    DSP48.DSP_[01].MASK[28] 27_94
    DSP48.DSP_[01].MASK[29] 26_96
    DSP48.DSP_[01].MASK[30] 27_102
    DSP48.DSP_[01].MASK[31] 26_104
    DSP48.DSP_[01].MASK[32] 27_106
    DSP48.DSP_[01].MASK[33] 26_108
    DSP48.DSP_[01].MASK[34] 27_110
    DSP48.DSP_[01].MASK[35] 26_112
    DSP48.DSP_[01].MASK[36] 27_127
    DSP48.DSP_[01].MASK[37] 26_129
    DSP48.DSP_[01].MASK[38] 26_132
    DSP48.DSP_[01].MASK[39] 27_133
    DSP48.DSP_[01].MASK[40] 26_136
    DSP48.DSP_[01].MASK[41] 27_137
    DSP48.DSP_[01].MASK[42] 27_144
    DSP48.DSP_[01].MASK[43] 26_146
    DSP48.DSP_[01].MASK[44] 26_149
    DSP48.DSP_[01].MASK[45] 27_150
    DSP48.DSP_[01].MASK[46] 26_153
    DSP48.DSP_[01].MASK[47] 26_154
    DSP48.DSP_[01].PATTERN[0] 26_01
    DSP48.DSP_[01].PATTERN[1] 26_04
    DSP48.DSP_[01].PATTERN[2] 26_05
    DSP48.DSP_[01].PATTERN[3] 27_08
    DSP48.DSP_[01].PATTERN[4] 26_09
    DSP48.DSP_[01].PATTERN[5] 26_12
    DSP48.DSP_[01].PATTERN[6] 27_17
    DSP48.DSP_[01].PATTERN[7] 26_20
    DSP48.DSP_[01].PATTERN[8] 27_21
    DSP48.DSP_[01].PATTERN[9] 27_24
    DSP48.DSP_[01].PATTERN[10] 26_26
    DSP48.DSP_[01].PATTERN[11] 26_29
    DSP48.DSP_[01].PATTERN[12] 27_40
    DSP48.DSP_[01].PATTERN[13] 26_43
    DSP48.DSP_[01].PATTERN[14] 27_44
    DSP48.DSP_[01].PATTERN[15] 26_47
    DSP48.DSP_[01].PATTERN[16] 27_48
    DSP48.DSP_[01].PATTERN[17] 26_51
    DSP48.DSP_[01].PATTERN[18] 26_57
    DSP48.DSP_[01].PATTERN[19] 26_60
    DSP48.DSP_[01].PATTERN[20] 27_61
    DSP48.DSP_[01].PATTERN[21] 26_64
    DSP48.DSP_[01].PATTERN[22] 27_65
    DSP48.DSP_[01].PATTERN[23] 26_68
    DSP48.DSP_[01].PATTERN[24] 26_86
    DSP48.DSP_[01].PATTERN[25] 27_88
    DSP48.DSP_[01].PATTERN[26] 26_90
    DSP48.DSP_[01].PATTERN[27] 27_92
    DSP48.DSP_[01].PATTERN[28] 26_94
    DSP48.DSP_[01].PATTERN[29] 26_97
    DSP48.DSP_[01].PATTERN[30] 27_101
    DSP48.DSP_[01].PATTERN[31] 27_104
    DSP48.DSP_[01].PATTERN[32] 26_106
    DSP48.DSP_[01].PATTERN[33] 27_108
    DSP48.DSP_[01].PATTERN[34] 26_110
    DSP48.DSP_[01].PATTERN[35] 27_112
    DSP48.DSP_[01].PATTERN[36] 26_127
    DSP48.DSP_[01].PATTERN[37] 26_130
    DSP48.DSP_[01].PATTERN[38] 27_131
    DSP48.DSP_[01].PATTERN[39] 26_134
    DSP48.DSP_[01].PATTERN[40] 27_135
    DSP48.DSP_[01].PATTERN[41] 26_138
    DSP48.DSP_[01].PATTERN[42] 26_144
    DSP48.DSP_[01].PATTERN[43] 27_146
    DSP48.DSP_[01].PATTERN[44] 26_148
    DSP48.DSP_[01].PATTERN[45] 26_151
    DSP48.DSP_[01].PATTERN[46] 27_152
    DSP48.DSP_[01].PATTERN[47] 26_155
    DSP48.DSP_[01].SEL_MASK_C 26_83
    DSP48.DSP_[01].SEL_MASK_ROUNDING_MODE1 27_82
    DSP48.DSP_[01].SEL_MASK_ROUNDING_MODE2 27_81 27_82
    DSP48.DSP_[01].USE_DPORT[0] 26_95
    DSP48.DSP_[01].USE_SIMD_FOUR12 26_143 27_52
    DSP48.DSP_[01].USE_SIMD_FOUR12_TWO24 26_84
    DSP48.DSP_[01].ZADREG[0] 27_95
    DSP48.DSP_[01].ZALUMODEREG[0] 26_54
    DSP48.DSP_[01].ZAREG_2_ACASCREG_1 26_139
    DSP48.DSP_[01].ZBREG_2_BCASCREG_1 27_49
    DSP48.DSP_[01].ZCARRYINREG[0] 26_02
    DSP48.DSP_[01].ZCARRYINSELREG[0] 27_10
    DSP48.DSP_[01].ZCREG[0] 26_76
    DSP48.DSP_[01].ZDREG[0] 27_93
    DSP48.DSP_[01].ZINMODEREG[0] 26_87
    DSP48.DSP_[01].ZIS_ALUMODE_INVERTED[0] 27_58
    DSP48.DSP_[01].ZIS_ALUMODE_INVERTED[1] 27_45
    DSP48.DSP_[01].ZIS_ALUMODE_INVERTED[2] 26_61
    DSP48.DSP_[01].ZIS_ALUMODE_INVERTED[3] 27_54
    DSP48.DSP_[01].ZIS_CARRYIN_INVERTED 27_09
    DSP48.DSP_[01].ZIS_CLK_INVERTED 27_77
    DSP48.DSP_[01].ZIS_INMODE_INVERTED[0] 27_118
    DSP48.DSP_[01].ZIS_INMODE_INVERTED[1] 27_119
    DSP48.DSP_[01].ZIS_INMODE_INVERTED[2] 27_66
    DSP48.DSP_[01].ZIS_INMODE_INVERTED[3] 27_69
    DSP48.DSP_[01].ZIS_INMODE_INVERTED[4] 27_53
    DSP48.DSP_[01].ZIS_OPMODE_INVERTED[0] 27_41
    DSP48.DSP_[01].ZIS_OPMODE_INVERTED[1] 26_44
    DSP48.DSP_[01].ZIS_OPMODE_INVERTED[2] 27_29
    DSP48.DSP_[01].ZIS_OPMODE_INVERTED[3] 27_22
    DSP48.DSP_[01].ZIS_OPMODE_INVERTED[4] 26_21
    DSP48.DSP_[01].ZIS_OPMODE_INVERTED[5] 26_19
    DSP48.DSP_[01].ZIS_OPMODE_INVERTED[6] 27_13
    DSP48.DSP_[01].ZMREG[0] 26_38
    DSP48.DSP_[01].ZOPMODEREG[0] 26_25
    DSP48.DSP_[01].ZPREG[0] 27_75

    """
    sites = []
    for dsp in sorted(dsps):
        if len(dsps[dsp]) > 0:
            sites.append(process_dsp_slice(top, dsps[dsp], dsp_features[dsp]))

