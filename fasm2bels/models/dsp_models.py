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

import fasm
from .verilog_modeling import Bel, Site, make_inverter_path
import math

def get_init(features, target_features, invert, width):
    """ Returns Attribute argument for specified feature.

    features: List of fasm.SetFeature objects
    target_feature (list[str]): Target feature (e.g. MASK or PATTERN).
        If multiple features are specified, first feature will be set at LSB.
    invert (bool): Controls whether output value should be bit inverted.
    width (int): Bit width of INIT value.

    Returns int

    """
    assert width % len(target_features) == 0, (width, len(target_features))

    final_init = 0
    for idx, target_feature in enumerate(target_features):
        init = 0
        for f in features:
            print(f"target_feature {target_feature}, feature {f.feature}")

            if target_feature in f.feature:
                for canon_f in fasm.canonical_features(f):
                    if canon_f.start is None:
                        init |= 1
                    else:
                        init |= (1 << canon_f.start)

        final_init |= init << idx * (width // len(target_features))

    if invert:
        final_init ^= (2**width) - 1

    return "{{width}}'h{{init:0{}X}}".format(int(math.ceil(width / 4))).format(
        width=width, init=final_init)

def get_dsp_site(db, grid, tile, target):
    """ Return the prjxray.tile.Site object for the given DSP site. """
    gridinfo = grid.gridinfo_at_tilename(tile)
    tile_type = db.get_tile_type(gridinfo.tile_type)
    
    target_type = 'DSP48E1'
    sites = tile_type.get_instance_sites(gridinfo)
    for site in sites:
        for site_pin in site.site_pins:
            if site.type == target_type and target in site_pin.wire:
                return site

    assert False, sites

def process_dsp_slice(top, features, set_features):
    aparts = features[0].feature.split('.')
    dsp_site = get_dsp_site(top.db, top.grid, aparts[0], aparts[2])
    site = Site(features, dsp_site)
    
    print(f"aparts {aparts}")
    bel = Bel('DSP48E1')
    bel.set_bel('DSP48E1')
    site.add_bel(bel, name='DSP48E1')
    site.override_site_type('DSP48E1')
    
    dsp_site = dsp_site.type == 'DSP48E1'
    
    parameter_binds = [
        ('MASK', ['MASK'], True, 48),
        ('PATTERN', ['PATTERN'], True, 48),
    ]
    
    for vparam, fparam, invert, width in parameter_binds:
        bel.parameters[vparam] = get_init(
            features, [p for p in fparam],
            invert=invert,
            width=width)

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

    # parameters
    AREG = 1
    if 'AREG_0' in set_features:
        AREG = 0
    elif 'AREG_2' in set_features:
        AREG = 2
    bel.parameters['AREG'] = AREG
    
    ACASCREG = 1
    if AREG == 0:
        ACASCREG = 0
    elif AREG == 1:
        ACASCREG = 1
    elif 'ZAREG_2_ACASCREG_1' in set_features:
        ACASCREG = 2
    bel.parameters['ACASCREG'] = ACASCREG

    ADREG = 1
    if 'ZADREG' in set_features:
        ADREG = 0
    bel.parameters['ADREG'] = ADREG
    
    ALUMODEREG = 1
    if 'ZALUMODEREG' in set_features:
        ALUMODEREG = 0
    bel.parameters['ALUMODEREG'] = ALUMODEREG
    
    BREG = 1
    if 'BREG_0' in set_features:
        BREG = 0
    elif 'BREG_2' in set_features:
        BREG = 2
    bel.parameters['BREG'] = BREG
    
    BCASCREG = 1
    if BREG == 0:
        BCASCREG = 0
    elif BREG == 1:
        BCASCREG = 1
    elif 'ZBREG_2_BCASCREG_1' in set_features:
        ACASCREG = 2
    bel.parameters['BCASCREG'] = BCASCREG
    
    CARRYINREG = 1
    if 'ZCARRYINREG' in set_features:
        CARRYINREG = 0
    bel.parameters['CARRYINREG'] = CARRYINREG
    
    CARRYINSELREG = 1
    if 'ZCARRYINSELREG' in set_features:
        CARRYINSELREG = 0
    bel.parameters['CARRYINSELREG'] = CARRYINSELREG
    
    CREG = 1
    if 'ZCREG' in set_features:
        CREG = 0
    bel.parameters['CREG'] = CREG 
    
    DREG = 1
    if 'ZDREG' in set_features:
        DREG = 0
    bel.parameters['DREG'] = DREG 
    
    INMODEREG = 1
    if 'ZINMODEREG' in set_features:
        INMODEREG = 0
    bel.parameters['INMODEREG'] = INMODEREG 
    
    MREG = 1
    if 'ZMREG' in set_features:
        MREG = 0
    bel.parameters['MREG'] = MREG 
    
    OPMODEREG = 1
    if 'ZOPMODEREG' in set_features:
        OPMODEREG = 0
    bel.parameters['OPMODEREG'] = OPMODEREG
    
    PREG = 1
    if 'ZPREG' in set_features:
        PREG = 0
    bel.parameters['PREG'] = PREG 
    
    
    # if the A/B_INPUT is present, we use DIRECT
    if 'A_INPUT' not in set_features:
        A_INPUT = '"CASCADE"'
    else:
        A_INPUT = '"DIRECT"' # default 
    
    if 'B_INPUT' not in set_features:
        B_INPUT = '"CASCADE"'
    else: 
        B_INPUT = '"DIRECT"'

    bel.parameters['A_INPUT'] = A_INPUT
    bel.parameters['B_INPUT'] = B_INPUT
    
    # DPORT
    if 'USE_DPORT' not in set_features:
        USE_DPORT = '"FALSE"'
    else:
        USE_DPORT = '"TRUE"'
    bel.parameters['USE_DPORT'] = USE_DPORT

    USE_MULT = '"MULTIPLY"'
    
    # USE_SIMD + override USE_MULT if necessary
    if 'USE_SIMD_FOUR12_TWO24' and 'USE_SIMD_FOUR12' in set_features:
        USE_SIMD = '"FOUR12"'
        USE_MULT = '"NONE"'
    elif 'USE_SIMD_FOUR12_TWO24' in set_features:
        USE_SIMD = '"TWO24"'
        USE_MULT = '"NONE"'
    else:
        USE_SIMD = '"ONE48"'

    bel.parameters['USE_SIMD'] = USE_SIMD
    bel.parameters['USE_MULT'] = USE_MULT

    # TODO FEATURE CONTROLS
    # 1. USE_MULT 
    # 2. AUTORESET_PATDET
    # 5. SEL_MASK
    # 6. SEL_PATTERN
    # 7. USE_PATTERN_DETECT
     
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
            #site_pips=site_pips,
            sink_site_type_pin=wire,
        )

    ##clock enable signals
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

     ## clk signal
    for wire in (
        'CLK',
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
        ("A", 30),
        ("ACIN", 30),
        ("B", 18),
        ("BCIN", 18),
        ("C", 48),
        ("CARRYINSEL", 3),
        ("D", 25),
        ("ALUMODE", 4),
        ("INMODE", 5),
        ("OPMODE", 7),
        ("PCIN", 48),
    ]

    for input_wire, width in input_wires:
        print(f"input wire {input_wire}, aparts[0] {aparts[0]}")
        if (input_wire == 'PCIN' or input_wire == 'ACIN' or input_wire == 'BCIN') and ('Y0' in aparts[0] and 'DSP_0' in aparts[2]): # can't have carry in for bottom most DSP
            continue

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
        ('PCOUT', 48),
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
        tile_features.add('.'.join(parts[2:]))

        if  'DSP_0_' in parts[1]:
            dsp_features['DSP_0'].add('.'.join(parts[1:]))
            dsps['DSP_0'].append(f)
        elif 'DSP_1_' in parts[1]:
            dsp_features['DSP_1'].add('.'.join(parts[1:]))
            dsps['DSP_1'].append(f)
        elif 'DSP_0' in parts[2]:
            dsp_features['DSP_0'].add(parts[3])
            dsps['DSP_0'].append(f)
        elif 'DSP_1' in parts[2]:
            dsp_features['DSP_1'].add(parts[3])
            dsps['DSP_1'].append(f)

    """
    DSP48E1 Config:

    DSP48.DSP_[01].A_INPUT[0] 27_84
    DSP48.DSP_[01].AREG_0 26_113 26_137 27_111
    DSP48.DSP_[01].AREG_2 27_136
    DSP48.DSP_[01].AUTORESET_PATDET_RESET 26_79
    DSP48.DSP_[01].AUTORESET_PATDET_RESET_NOT_MATCH 26_78
    DSP48.DSP_[01].B_INPUT[0] 26_11
    DSP48.DSP_[01].BREG_0 26_40 26_48 27_38
    DSP48.DSP_[01].BREG_2 27_47
    DSP48.DSP_[01].MASK[47:0] 
    DSP48.DSP_[01].PATTERN[47:0] 
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
    DSP48.DSP_[01].ZIS_ALUMODE_INVERTED[3:0] 
    DSP48.DSP_[01].ZIS_CARRYIN_INVERTED 27_09
    DSP48.DSP_[01].ZIS_CLK_INVERTED 27_77
    DSP48.DSP_[01].ZIS_INMODE_INVERTED[4:0] 
    DSP48.DSP_[01].ZIS_OPMODE_INVERTED[6:0] 
    DSP48.DSP_[01].ZMREG[0] 26_38
    DSP48.DSP_[01].ZOPMODEREG[0] 26_25
    DSP48.DSP_[01].ZPREG[0] 27_75

    """
    sites = []
    for dsp in sorted(dsps):
        if len(dsps[dsp]) > 0:
            sites.append(process_dsp_slice(top, dsps[dsp], dsp_features[dsp]))


