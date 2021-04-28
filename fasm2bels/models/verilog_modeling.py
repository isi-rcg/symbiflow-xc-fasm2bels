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

import functools
import re
import fasm
from .utils import make_bus, flatten_wires, unescape_verilog_name, escape_verilog_name
from fasm2bels.make_routes import make_routes, ONE_NET, ZERO_NET, prune_antennas
from fasm2bels.database.connection_db_utils import get_wire_pkey, create_maybe_get_wire
from ..lib.interchange import create_site_routing
""" Core classes for modelling a bitstream back into verilog and routes.

There are 3 modelling elements:

 - Bel: A synthesizable element.
 - Site: A collection of Bel's, routing sinks and routing sources.
 - Module: The root container for all Sites

The modelling approach works as so:

BELs represent a particular tech library instance (e.g. LUT6 or FDRE).  These
BELs are connected into the routing fabric or internal site sources via the
Site methods:

 - Site.add_sink
 - Site.add_source
 - Site.add_output_from_internal
 - Site.connect_internal
 - Site.add_internal_source

BEL parameters should be on the BEL.

In cases where there is multiple instances of a BEL (e.g. LUT's), the
Bel.set_bel must be called to ensure that Vivado places the BEL in the exact
location.

"""


def pin_to_wire_and_idx(pin):
    """ Break pin name into wire name and vector index.

    Arguments
    ---------
    pin : str
        Pin name, with optional vector index.

    Returns
    -------
    wire : str
        Wire name
    idx : int
        Vector index

    >>> pin_to_wire_and_idx('A')
    ('A', None)
    >>> pin_to_wire_and_idx('A[0]')
    ('A', 0)
    >>> pin_to_wire_and_idx('A[1]')
    ('A', 1)

    """
    idx = pin.find('[')
    if idx == -1:
        return (pin, None)
    else:
        assert pin[-1] == ']'
        return (pin[:idx], int(pin[idx + 1:-1]))


class ConnectionModel(object):
    """ Constant, Wire, Bus and NoConnect objects represent a small interface
    for Verilog module instance connection descriptions.
    """

    def to_string(self, net_map=None):
        """ Returns the string representing this models connection in verilog.

        Arguments
        ---------
        net_map : map of str to str
            Optional wire renaming map.  If present, leaf wires should be
            renamed through the map.

        Returns
        -------
        str representing valid Verilog to model the connect by this object.

        """
        pass

    def iter_wires(self):
        """ Iterates over wires present on this object.

        Yields
        ------
        Vector index : int
            Is None for scalar connections, otherwise an integer that
            represents the index into the vector.
        Connection : str
            Verilog representing this connection.

        """
        pass

    def output_interchange(self, parent_cell, instance_name, port,
                           constant_nets, net_map):
        """ Output interchange format for connection.

        parent_cell : Cell python object
            Cell that contains this connection.

        instance_name : str
            Name of cell instance that this connection belongs too.

        port : str
            Name of port on cell instance this connection is connected too.

        constant_nets : dict
            Map of 0/1 to net names for constants nets (e.g.
            {0: "<const0>", 1: "<const1>"}).

        net_map : map of str to str
            Optional wire renaming map.  If present, leaf wires should be
            renamed through the map.

        idx : int, optional
            Bus index for bussed ports, should be None otherwise.

        """
        pass

    def bus_width(self):
        """ Returns the width of the bus if a bussed port, otherwise None. """
        pass


class Constant(ConnectionModel):
    """ Represents a boolean constant, e.g. 1'b0 or 1'b1. """

    def __init__(self, value):
        assert value in [0, 1]
        self.value = value

    def to_string(self, net_map=None):
        return "1'b{}".format(self.value)

    def __repr__(self):
        return 'Constant({})'.format(self.value)

    def iter_wires(self):
        return iter([])

    def output_interchange(self,
                           parent_cell,
                           instance_name,
                           port,
                           constant_nets,
                           net_map,
                           idx=None):
        parent_cell.connect_net_to_instance(
            net_name=constant_nets[self.value],
            instance_name=instance_name,
            port=port,
            idx=idx)

    def bus_width(self):
        return None


class Wire(ConnectionModel):
    """ Represents a single wire connection. """

    def __init__(self, wire):
        self.wire = wire

    def to_string(self, net_map=None):
        if net_map is None:
            return self.wire
        else:
            if self.wire in net_map:
                return net_map[self.wire]
            else:
                return self.wire

    def __repr__(self):
        return 'Wire({})'.format(repr(self.wire))

    def iter_wires(self):
        yield (None, self.wire)

    def output_interchange(self,
                           parent_cell,
                           instance_name,
                           port,
                           constant_nets,
                           net_map,
                           idx=None):
        net_name = unescape_verilog_name(self.to_string(net_map))

        if net_name == "1'b1":
            net_name = constant_nets[1]
        elif net_name == "1'b0":
            net_name = constant_nets[0]

        parent_cell.connect_net_to_instance(
            net_name=net_name, instance_name=instance_name, port=port, idx=idx)

    def bus_width(self):
        return None


class Bus(ConnectionModel):
    """ Represents a vector wire connection.

    Arguments
    ---------
    wires : list of Constant or Wire objects.

    """

    def __init__(self, wires):
        self.wires = wires

    def to_string(self, net_map=None):
        return '{' + ', '.join(
            wire.to_string(net_map=net_map) for wire in self.wires[::-1]) + '}'

    def __repr__(self):
        return 'Bus({})'.format(repr(self.wires))

    def iter_wires(self):
        for idx, wire in enumerate(self.wires):
            for _, real_wire in wire.iter_wires():
                yield (idx, real_wire)

    def output_interchange(self, parent_cell, instance_name, port,
                           constant_nets, net_map):
        for idx, wire in enumerate(self.wires):
            wire.output_interchange(parent_cell, instance_name, port,
                                    constant_nets, net_map, idx)

    def bus_width(self):
        return len(self.wires)


class NoConnect(ConnectionModel):
    """ Represents an unconnected port. """

    def __init__(self):
        pass

    def to_string(self, net_map=None):
        return ''

    def __repr__(self):
        return 'NoConnect()'

    def iter_wires(self):
        return iter([])

    def output_interchange(self,
                           parent_cell,
                           instance_name,
                           port,
                           constant_nets,
                           net_map,
                           idx=None):
        pass

    def bus_width(self):
        return None


class Bel(object):
    """ Object to model a BEL. """

    def __init__(self, module, name=None, keep=True, priority=0):
        """ Construct Bel object.

        module (str): Exact tech library name to instance during synthesis.
            Example "LUT6_2" or "FDRE".
        name (str): Optional name of this bel, used to disambiguate multiple
            instances of the same module in a site.  If there are multiple
            instances of the same module in a site, name must be specified and
            unique.
        keep (bool): Controls if KEEP, DONT_TOUCH constraints are added to this
            instance.
        priority (int): Priority for assigning LOC attributes.  Lower priority
            means LOC is set first.  LOC priority should be set to allow
            assignment without blocking later elements.

        """
        self.module = module
        if name is None:
            self.name = module
        else:
            self.name = name
        self.connections = {}
        self.unused_connections = set()
        self.parameters = {}
        self.outputs = set()
        self.prefix = None
        self.site = None
        self.keep = keep
        self.bel = None
        self.nets = None
        self.net_names = {}
        self.priority = priority
        self.parent_cell = None

        # Map of (bel_name, bel_pin) -> cell_pin name
        self.bel_pins_to_cell_pins = {}

        # List of other bels named in bel_pins_to_cell_pins map.
        # This list is used to populate some bel_name -> Bel object maps, so
        # this set does need to be correct.
        self.other_bels = set()

        # A list of BELs to be used when placing this Bel object within a
        # design.  This is generally used to model cell mapping at load
        # (e.g. LUT6_2 -> (LUT6, LUT5)).
        self.physical_bels = []

        # When using a cell mapping, any nets that source from the mapping
        # cell will be renamed.  This map should be populated with any remaps.
        # Map of (bel_name, bel_pin) -> net name.
        self.physical_net_names = {}

        # Map of cell pins -> net_names, as determined during
        # output_site_routing.
        #
        # This map properly accounts for any physical_bels and
        # physical_net_names present in the Bel object.
        self.final_net_names = {}

        # Port widths for connections that are sometimes narrower.
        self.port_width = {}
        self.port_direction = {}

    def set_parent_cell(self, parent_cell):
        """ Set parent cell for this object.

        This only modifies what cell name this object returns.  If a parent
        is set, this object returns the name of the parent cell.

        """
        self.parent_cell = parent_cell

    def set_port_width(self, port, width):
        """ Explicitly set the width of a port, in the event that not all bits will be connected. """
        self.port_width[port] = width

    def add_unconnected_port(self, port, width, direction):
        """ Add a port to this cell that is unconnected.

        port : str
            Port that is unconnected

        width : int or None
            For bussed ports, the width of the port, otherwise None for bitty
            ports.

        direction : str
            Should be either "input", "output", or "inout".
            is an input.

        """
        assert port not in self.connections
        self.port_direction[port] = direction
        self.set_port_width(port, width)

    def set_prefix(self, prefix):
        """ Set the prefix used for wire and BEL naming.

        This is method is typically called automatically during
        Site.integrate_site. """
        self.prefix = prefix

    def set_site(self, site):
        """ Sets the site string used to set the LOC constraint.

        This is method is typically called automatically during
        Site.integrate_site. """
        self.site = site

    def set_bel(self, bel):
        """ Sets the BEL constraint.

        This method should be called if the parent site has multiple instances
        of the BEL (e.g. LUT6 in a SLICE).
        """
        self.bel = bel

    def _prefix_things(self, s):
        """ Apply the prefix (if any) to the input string. """
        if self.prefix is not None:
            return '{}_{}'.format(self.prefix, s)
        else:
            return s

    def get_prefixed_name(self):
        return self._prefix_things(self.name)

    def get_cell(self, top):
        """ Get the cell name of this BEL.

        Should only be called after set_prefix has been invoked (if set_prefix
        will be called)."""

        if self.parent_cell is not None:
            return self.parent_cell.get_cell(top)

        # The .cname property will be associated with some pin/net combinations
        # Use this name if present.

        eblif_cnames = set()
        for ((pin, idx), net) in self.net_names.items():
            cname = top.lookup_cname(pin, idx, net)
            if cname is not None:
                eblif_cnames.add(cname)

        if len(eblif_cnames) > 0:
            # Always post-fix with the programatic name to allow for easier
            # cell lookup via something like "*{name}"
            return escape_verilog_name('_'.join(eblif_cnames) +
                                       self._prefix_things(self.name))
        else:
            return self._prefix_things(self.name)

    def create_connections(self, top):
        """ Create connection model for this BEL.

        Returns
        -------
        dead_wires : list of str
            List of wires that represents unconnected input or output wires
            in vectors on this BEL.
        connections : map of str to ConnectionModel
        bus_is_output : map of wire or bus name to whether it is an output.

        """
        connections = {}
        buses = {}
        bus_is_output = {}

        for wire, connection in self.connections.items():
            if top.is_top_level(connection):
                connection_wire = Wire(connection)
            elif connection in [0, 1]:
                connection_wire = Constant(connection)
            else:
                if connection is not None:
                    connection_wire = Wire(self._prefix_things(connection))
                else:
                    connection_wire = None

            if '[' in wire:
                bus_name, address = wire.split('[')
                assert address[-1] == ']', address

                wire_is_output = wire in self.outputs
                if bus_name not in buses:
                    buses[bus_name] = {}
                    bus_is_output[bus_name] = wire_is_output
                else:
                    assert bus_is_output[bus_name] == wire_is_output, (
                        bus_name,
                        wire,
                        bus_is_output[bus_name],
                        wire_is_output,
                    )

                if connection_wire is not None:
                    buses[bus_name][int(address[:-1])] = connection_wire
                else:
                    buses[bus_name][int(address[:-1])] = None
            else:
                if connection_wire is None:
                    connection_wire = NoConnect()
                connections[wire] = connection_wire
                bus_is_output[wire] = wire in self.outputs

        dead_wires = []

        for bus_name, bus in buses.items():
            prefix_bus_name = self._prefix_things(bus_name)
            num_elements = max(bus.keys()) + 1
            bus_wires = [None for _ in range(num_elements)]
            for idx, wire in bus.items():
                bus_wires[idx] = wire

            for idx, wire in enumerate(bus_wires):
                if wire is None:
                    dead_wire = '_{}_{}_'.format(prefix_bus_name, idx)
                    dead_wires.append(dead_wire)
                    bus_wires[idx] = Wire(dead_wire)

            connections[bus_name] = Bus(bus_wires)

        for unused_connection in self.unused_connections:
            connections[unused_connection] = NoConnect()

        return dead_wires, connections, bus_is_output

    def make_net_map(self, top, net_map):
        """ Create a mapping of programatic net names to VPR net names.

        By default nets are named:

        {tile}_{site}_{pin}{pin idx}

        For example:

        CLBLL_L_X12Y110_SLICE_X16Y110_BO5

        This scheme unambiguously names a connection in the design.  Initially
        all nets and BELs are defined using this scheme to provide a simple
        unambiguous way to refer to wires in the design.

        However the parent design maybe have assigned wires net names from the,
        e.g. '$auto$alumacc.cc:474:replace_alu$1273.CO_CHAIN [1]'. This
        function builds the association between these two schemes using the
        pin to net mapping created via Bel.add_net_name. Bel.add_net_name is
        called during site integration to associate Bel pins with net names
        via the wire primary key table in the connection database.

        During verilog output, the net map can be used to translate the
        programatic names back to the net names from the eblif used during
        place and route.

        """
        _, connections, _ = self.create_connections(top)

        for pin, connection in connections.items():
            for idx, wire in connection.iter_wires():
                key = (pin, idx)

                if key in self.net_names:
                    if wire in net_map:
                        assert self.net_names[key] == net_map[wire], (
                            key, self.net_names[key], net_map[wire])
                    else:
                        net_map[wire] = self.net_names[key]

    def output_verilog(self, top, net_map, indent='  '):
        """ Output the Verilog to represent this BEL. """

        if self.parent_cell is not None:
            return

        dead_wires, connections, _ = self.create_connections(top)

        for dead_wire in dead_wires:
            yield '{indent}wire [0:0] {wire};'.format(
                indent=indent, wire=dead_wire)

        yield ''

        if self.site is not None:
            comment = []
            if self.keep:
                comment.append('KEEP')
                comment.append('DONT_TOUCH')

            if self.bel:
                comment.append('BEL = "{bel}"'.format(bel=self.bel))

            yield '{indent}(* {comment} *)'.format(
                indent=indent, comment=', '.join(comment))

        yield '{indent}{site} #('.format(indent=indent, site=self.module)

        parameters = []
        for param, value in sorted(
                self.parameters.items(), key=lambda x: x[0]):
            parameters.append('{indent}{indent}.{param}({value})'.format(
                indent=indent, param=param, value=value))

        if parameters:
            yield ',\n'.join(parameters)

        yield '{indent}) {name} ('.format(
            indent=indent, name=self.get_cell(top))

        if connections:
            yield ',\n'.join(
                '.{}({})'.format(port, connections[port].to_string(net_map))
                for port in sorted(connections))

        yield '{indent});'.format(indent=indent)

    def output_interchange(self, top_cell, top, net_map, constant_nets):
        """ Output this object into an interchange CellInstance.

        top_cell : logical_netlist.Cell
            Interchange logical netlist Cell that contains this object

        top : Module

        net_map : map of str to str
            Optional wire renaming map.  If present, leaf wires should be
            renamed through the map.

        constant_nets : dict
            Map of 0/1 to net names for constants nets (e.g.
            {0: "<const0>", 1: "<const1>"}).

        """
        if self.parent_cell is not None:
            return

        dead_wires, connections, _ = self.create_connections(top)

        for wire in dead_wires:
            top_cell.add_net(unescape_verilog_name(wire))

        cell_instance = unescape_verilog_name(self.get_cell(top))

        top_cell.add_cell_instance(
            name=cell_instance,
            cell_name=self.module,
            property_map=self.parameters)

        if connections:
            for port in connections:
                connections[port].output_interchange(
                    parent_cell=top_cell,
                    instance_name=cell_instance,
                    port=port,
                    constant_nets=constant_nets,
                    net_map=net_map)

    def add_net_name(self, pin, net_name):
        """ Add name of net attached to this pin ."""
        assert pin not in self.net_names
        key = pin_to_wire_and_idx(pin)
        self.net_names[key] = net_name

    def unmap_bel_pin(self, bel_name, bel_pin):
        """ Remove BEL pin to Cell pin mapping.

        This is useful for connections that get cleaned up after make_routes
        process.  For example RAMB18E1.WEBWE[4-7].

        """
        key = bel_name, bel_pin
        del self.bel_pins_to_cell_pins[key]

    def remap_bel_pin_to_cell_pin(self, bel_name, bel_pin, cell_pin):
        """ Remap BEL pin to Cell pin.

        Unlike map_bel_pin_to_cell_pin, this will allow renaming of BEL pin to
        Cell pin mapping.

        """
        key = bel_name, bel_pin
        self.bel_pins_to_cell_pins[key] = cell_pin

    def map_bel_pin_to_cell_pin(self, bel_name, bel_pin, cell_pin):
        """ Map a BEL pin to a Cell pin contained within this object. """
        key = bel_name, bel_pin
        if key in self.bel_pins_to_cell_pins:
            assert self.bel_pins_to_cell_pins[key] == cell_pin, (key, cell_pin)
        else:
            self.bel_pins_to_cell_pins[key] = cell_pin

        if bel_name != self.bel:
            self.other_bels.add(bel_name)

    def add_physical_bel(self, physical_bel):
        """ Add a Bel object to be used to place this object in the design.

        physical_bel : Bel object

        """
        self.physical_bels.append(physical_bel)

    def get_physical_net_name(self, instance_name, bel_name, bel_pin):
        """ Maps a BEL pin to a net name if a physical net rename is required.

        instance_name : str
            Instance name for this Bel object

        bel_name : str
            Which BEL does the BEL pin being queried belong too?

        bel_pin : str
            Which BEL pin is being queried?

        Returns a str with the physical net name or None if no mapping exists.

        """
        key = (bel_name, bel_pin)
        physical_net_name = self.physical_net_names.get(key, None)

        if physical_net_name:
            return instance_name + '/' + physical_net_name


class Site(object):
    """ Object to model a Site.

    A site is a collection of BELs, and sources and sinks that connect the
    site to the routing fabric.  Sources and sinks exported by the Site will
    be used during routing formation.

    Wires that are not in the sources and sinks lists will be invisible to
    the routing formation step.  In particular, site connections that should
    be sources and sinks but are not specified will be ingored during routing
    formation, and likely end up as disconnected wires.

    On the flip side it is import that specified sinks are always connected
    to at least one BEL.  If this is not done, antenna nets may be emitted
    during routing formation, which will result in a DRC violation.

    Parameters
    ----------
    merged_site : bool
        Set to true if this site spans multiple sites (e.g. BRAM36 spans
        BRAM18_Y0 and BRAM18_Y1), versus a SLICEL, which stays within its
        SLICE_X0.

    """

    def __init__(self, features, site, tile=None, merged_site=False):
        self.bels = []
        self.sinks = {}
        self.sources = {}
        self.outputs = {}
        self.internal_sources = {}

        # Map of internal source name to site routing tuple.
        self.internal_source_bel_pins = {}

        self.set_features = set()
        self.features = set()
        self.post_route_cleanup = None
        self.bel_map = {}

        self.site_wire_to_wire_pkey = {}
        self.site_type_pins = {}

        if features:
            aparts = features[0].feature.split('.')

            for f in features:
                if f.value == 0:
                    continue

                if merged_site:
                    parts = f.feature.split('.')
                    assert parts[0] == aparts[0]
                    self.set_features.add(
                        fasm.SetFasmFeature(
                            feature='.'.join(parts[1:]),
                            start=f.start,
                            end=f.end,
                            value=f.value,
                            value_format=f.value_format,
                        ))
                else:
                    parts = f.feature.split('.')
                    #assert parts[0] == aparts[0]
                    #assert parts[1] == aparts[1]
                    self.set_features.add(
                        fasm.SetFasmFeature(
                            feature='.'.join(parts[2:]),
                            start=f.start,
                            end=f.end,
                            value=f.value,
                            value_format=f.value_format,
                        ))

        # Features as strings
        self.features = set([f.feature for f in self.set_features])

        if tile is None:
            self.tile = aparts[0]
        else:
            self.tile = tile

        self.site = site

        # When site_type_override is not None, this site type will be used
        # instead of self.site.type.
        #
        # This is typically used when the default site type is too generic,
        # e.g. IOB33M -> IOB33.
        self.site_type_override = None

        # Map of source site routing tuple to set of site routing tuples that
        # are downstream from the source.
        self.site_routing = {}

    def override_site_type(self, site_type):
        """ Set the site type override for this site.

        site_type : str
            Site type to use instead of self.site.type

        """
        self.site_type_override = site_type

    def site_type(self):
        """ Get the site type for this object. """
        if self.site_type_override is None:
            return self.site.type
        else:
            return self.site_type_override

    def link_site_routing(self, site_routing):
        """ Add a site routing path.

        site_routing : list of site routing tuples
            This list should directly path in the site routing graph.
            site_routing[0] should lead to site_routing[1], site_routing[1]
            should lead to site_routing[2].  This **is** directed, so the
            order matters.

        """
        for src, dest in zip(site_routing, site_routing[1:]):
            if src not in self.site_routing:
                self.site_routing[src] = set()

            self.site_routing[src].add(dest)

    def prune_site_routing(self, key):
        """ Remove a site routing tuple from the site routing graph. """
        for sinks in self.site_routing.values():
            if key in sinks:
                sinks.remove(key)

        def remove_drivers(key):
            if key in self.site_routing:
                children = self.site_routing[key]
                del self.site_routing[key]

                for child in children:
                    remove_drivers(child)

        remove_drivers(key)

    def output_site_routing(self, top, parent_cell, net_map, constant_nets,
                            sub_cell_nets):
        """ Convert site routing to Physical* nets.

        top : Module

        parent_cell : logical_netlist.Cell
            Cell that contains this Bel.

        net_map : map of str to str
            Optional wire renaming map.  If present, leaf wires should be
            renamed through the map.

        constant_nets : dict
            Map of 0/1 to net names for constants nets (e.g.
            {0: "<const0>", 1: "<const1>"}).

        Returns dict of nets to Physical* objects that represent the site
        local sources for that net.

        """

        # Map of bel_name in this site -> Bel objects.
        bel_map = {}

        # Map of bel_name in this site -> instance name.
        instance_names = {}

        for bel in self.bels:
            instance_name = unescape_verilog_name(bel.get_cell(top))
            if bel.bel is not None:
                assert bel.bel not in bel_map, (bel.module, bel.bel)
                bel_map[bel.bel] = bel
                instance_names[bel.bel] = instance_name

            for other_bel in bel.other_bels:
                assert other_bel not in bel_map
                bel_map[other_bel] = bel
                instance_names[other_bel] = instance_name

        # Gather all BEL pins in this site.
        bel_pins = set()
        # Also create a map from destination site routing tuple to source
        # site routing tuple.
        dest_to_src = {}

        for parent in self.site_routing:
            if parent[0] == 'bel_pin':
                bel_pins.add(parent)

            for child in self.site_routing[parent]:
                if child[0] == 'bel_pin':
                    bel_pins.add(child)

                if child in dest_to_src:
                    assert dest_to_src[child] == parent, (child, parent,
                                                          dest_to_src[child])

                dest_to_src[child] = parent

        # At this point, the root of each site routing net needs to be
        # identied, and for each root the net name needs to be determined.
        #
        # net_roots is the map of root site routing tuple to net name.
        net_roots = {}

        # Some "primatives" actually get transformed upon loading, e.g. LUT6_2.
        # This appear to Vivado as nets sourcing from a cell below the root
        # cell.
        #
        # This map converts the top-level net to the net from within the
        # transformed cell.
        bel_pin_to_net_root = {}

        # To ensure that all site routing roots are found, start from each
        # bel pin, and walk to it's root.
        #
        # If the bel pin is a source, it will be it's own root.
        # If the bel pin is a sink, it will source from another site routing
        # tuple.
        for bel_pin_key in bel_pins:
            site_routing_type, bel_name, bel_pin, direction = bel_pin_key
            assert site_routing_type == 'bel_pin'

            if direction == 'site_source':
                continue

            # If the bel_name isn't in the bel_map, this site routing is
            # likely dead, so ignore it.
            if bel_name not in bel_map:
                continue

            bel = bel_map[bel_name]
            instance_name = instance_names[bel_name]

            # If no BEL pin -> Cell pin mapping has been made, this site
            # routing is also likely dead, so ignore it.
            key = bel_name, bel_pin
            if key not in bel.bel_pins_to_cell_pins:
                continue

            # Map the BEL pin back to a net name.
            cell_pin = bel.bel_pins_to_cell_pins[bel_name, bel_pin]
            net_name = parent_cell.get_net_name(instance_name, cell_pin)

            # In the event there is physical BELs in play, also get the
            # physical net name to be used.
            #
            # To avoid mapping mismatches, wait until after all BEL pins have
            # been mapped to translate from net_name to physical net name.
            sub_net_name = bel.get_physical_net_name(instance_name, bel_name,
                                                     bel_pin)

            if net_name is None:
                assert sub_net_name is not None, (instance_name, bel_name,
                                                  bel_pin, cell_pin,
                                                  bel.physical_net_names)
                net_name = sub_net_name
                sub_net_name = None

            if sub_net_name is not None:
                # Make sure mapping is unique.
                if net_name in sub_cell_nets:
                    assert sub_cell_nets[net_name] == sub_net_name
                else:
                    sub_cell_nets[net_name] = sub_net_name

            # Walk back to the source in the site routing graph.
            key = bel_pin_key
            while key in dest_to_src:
                key = dest_to_src[key]

            # Create a map from BEL pin to net root within the site.
            bel_pin_to_net_root[bel_pin_key] = key

            # Check that the net name for this BEL pin matches the previous
            # net name or store it.
            if key in net_roots:
                assert net_roots[key] == net_name, (key, net_roots[key],
                                                    net_name)
            else:
                net_roots[key] = net_name

        # Now that final net names have been assigned to net roots, populate
        # final_net_names.
        for bel_pin_key in bel_pins:
            site_routing_type, bel_name, bel_pin, direction = bel_pin_key
            assert site_routing_type == 'bel_pin'

            if bel_pin_key not in bel_pin_to_net_root:
                continue

            root_key = bel_pin_to_net_root[bel_pin_key]
            if root_key not in net_roots:
                continue

            net_name = net_roots[root_key]

            if bel_name not in bel_map:
                continue

            bel = bel_map[bel_name]
            cell_pin = bel.bel_pins_to_cell_pins[bel_name, bel_pin]

            if cell_pin in bel.final_net_names:
                assert bel.final_net_names[cell_pin] == net_name
            else:
                bel.final_net_names[cell_pin] = net_name

        # Convert site_routing tree into Physical* object tree.
        return create_site_routing(self.site, net_roots, self.site_routing,
                                   constant_nets)

    def has_feature(self, feature):
        """ Does this set have the specified feature set? """
        return feature in self.features

    def has_feature_with_part(self, part):
        """
        Returns True when a given site has a feature which contains a
        particular part.
        """
        for feature in self.features:
            parts = feature.split(".")
            if part in parts:
                return True

        return False

    def has_feature_containing(self, substr):
        """
        Returns True when a given site has a feature which contains a given
        substring.
        """
        for feature in self.features:
            if substr in feature:
                return True

        return False

    def decode_multi_bit_feature(self, feature):
        """
        Decodes a "multi-bit" fasm feature. If not present returns 0.

        >>> site = Site(features=[
        ...         fasm.SetFasmFeature(
        ...             feature="TILE.CELL.VAL", start=0, end=10, value=682,
        ...             value_format=None),
        ...     ], site=None)
        >>> site.decode_multi_bit_feature("VAL")
        682
        >>> site = Site(features=[
        ...         fasm.SetFasmFeature(
        ...             feature="TILE.CELL.VAL", start=0, end=0, value=1,
        ...             value_format=None),
        ...         fasm.SetFasmFeature(
        ...             feature="TILE.CELL.VAL", start=2, end=2, value=1,
        ...             value_format=None),
        ...     ], site=None)
        >>> site.decode_multi_bit_feature("VAL")
        5
        >>> site = Site(features=[
        ...         fasm.SetFasmFeature(
        ...             feature="TILE.CELL.VAL", start=0, end=1, value=2,
        ...             value_format=None),
        ...         fasm.SetFasmFeature(
        ...             feature="TILE.CELL.VAL", start=2, end=3, value=3,
        ...             value_format=None),
        ...     ], site=None)
        >>> site.decode_multi_bit_feature("VAL")
        14
        """

        value = 0

        for f in self.set_features:
            if f.feature == feature:
                for canon_f in fasm.canonical_features(f):
                    if canon_f.start is None:
                        value |= 1
                    else:
                        value |= (1 << canon_f.start)

        return value

    def add_sink(self,
                 bel,
                 cell_pin,
                 sink_site_pin,
                 bel_name,
                 bel_pin,
                 site_pips=[],
                 sink_site_type_pin=None,
                 real_cell_pin=None):
        """ Adds a sink.

        Attaches sink to the specified bel.

        bel (Bel): Bel object
        cell_pin (str): The exact tech library name for the relevant pin.
            Can be a bus (e.g. A[5]).  The name must identically match the
            library name or an error will occur during synthesis.
        sink_site_pin (str): The exact site pin name for this sink.  The name
            must identically match the site pin name, or an error will be
            generated when Site.integrate_site is invoked.
        bel_name (str): Name of the BEL this cell pin is mapped too.
        bel_pin (str): Name of the BEL pin this cell pin is mapped too.
        site_pips (list): List of site routing tuples used to connect site pin
            to BEL pin.
        sink_site_type_pin (str): In cases where a site pin is renamed when
            the site type is changed (e.g. FIFO18E1 -> RAMB18E1), this is the
            site pin name in the override site type, rather than the default
            site type.

        """

        assert cell_pin not in bel.connections, cell_pin

        if sink_site_pin not in self.sinks:
            self.sinks[sink_site_pin] = []

        bel.connections[cell_pin] = sink_site_pin
        bel.map_bel_pin_to_cell_pin(
            bel_name=bel_name,
            bel_pin=bel_pin,
            cell_pin=cell_pin if real_cell_pin is None else real_cell_pin)
        self.sinks[sink_site_pin].append((bel, cell_pin))

        if sink_site_type_pin is not None:
            self.site_type_pins[sink_site_type_pin] = sink_site_pin
            sink_site_pin = sink_site_type_pin
        else:
            self.site_type_pins[sink_site_pin] = sink_site_pin

        self.link_site_routing([('site_pin', sink_site_pin),
                                ('bel_pin', sink_site_pin, sink_site_pin,
                                 'site_source')] + site_pips +
                               [('bel_pin', bel_name, bel_pin, 'input')])

    def mask_sink(self, bel, bel_pin):
        """ Mark a BEL pin as not visible in the Verilog.

        This bel_pin is effectively removed from the Verilog output, but
        may still be routed too during FIXED_ROUTE emission.
        """
        assert bel_pin in bel.connections

        sink = bel.connections[bel_pin]

        sink_idx = None
        for idx, (a_bel, a_bel_pin) in enumerate(self.sinks[sink]):
            if a_bel is bel and bel_pin == a_bel_pin:
                assert sink_idx is None
                sink_idx = idx

        assert sink_idx is not None, (bel, bel_pin, sink)
        self.sinks[sink][sink_idx] = None
        del bel.connections[bel_pin]

    def rename_sink(self, bel, old_bel_pin, new_bel_pin):
        """ Rename a BEL sink from one pin name to another.

        new_bel_pin may be a mask'd sink BEL pin.

        """
        self.move_sink(bel, old_bel_pin, bel, new_bel_pin)

    def move_sink(self, old_bel, old_bel_pin, new_bel, new_bel_pin):
        """ Moves sink from one BEL in site to another BEL in site.

        new_bel_pin may be a mask'd sink BEL pin.

        """
        assert old_bel_pin in old_bel.connections
        assert new_bel_pin not in new_bel.connections

        new_bel.connections[new_bel_pin] = old_bel.connections[old_bel_pin]
        sink = old_bel.connections[old_bel_pin]
        del old_bel.connections[old_bel_pin]

        sink_idx = None
        for idx, (a_bel, a_bel_pin) in enumerate(self.sinks[sink]):
            if a_bel is old_bel and a_bel_pin == old_bel_pin:
                assert sink_idx is None
                sink_idx = idx

        assert sink_idx is not None, (old_bel, old_bel_pin, sink)
        self.sinks[sink][sink_idx] = (new_bel, new_bel_pin)

    def add_source(self,
                   bel,
                   cell_pin,
                   source_site_pin,
                   bel_name,
                   bel_pin,
                   site_pips=[],
                   source_site_type_pin=None):
        """ Adds a source.

        Attaches source to bel.

        bel (Bel): Bel object
        cel_pin (str): The exact tech library name for the relevant pin.  Can be
            a bus (e.g. A[5]).  The name must identically match the library
            name or an error will occur during synthesis.
        source_site_pin (str): The exact site pin name for this source.  The
            name mustidentically match the site pin name, or an error will be
            generated when Site.integrate_site is invoked.
        bel_name (str): Name of the BEL this cell pin is mapped too.
        bel_pin (str): Name of the BEL pin this cell pin is mapped too.
        site_pips (list): List of site routing tuples used to connect the BEL
            pin to the site pin.
        source_site_type_pin (str): In cases where a site pin is renamed when
            the site type is changed (e.g. FIFO18E1 -> RAMB18E1), this is the
            site pin name in the override site type, rather than the default
            site type.

        """
        assert source_site_pin not in self.sources
        assert cell_pin not in bel.connections

        bel.connections[cell_pin] = source_site_pin
        bel.outputs.add(cell_pin)
        self.sources[source_site_pin] = (bel, cell_pin)
        bel.map_bel_pin_to_cell_pin(
            bel_name=bel_name, bel_pin=bel_pin, cell_pin=cell_pin)

        if source_site_type_pin is not None:
            self.site_type_pins[source_site_type_pin] = source_site_pin
            source_site_pin = source_site_type_pin
        else:
            self.site_type_pins[source_site_pin] = source_site_pin

        self.link_site_routing([('bel_pin', bel_name, bel_pin,
                                 'output')] + site_pips +
                               [('bel_pin', source_site_pin, source_site_pin,
                                 'input'), ('site_pin', source_site_pin)])

    def rename_source(self, bel, old_bel_pin, new_bel_pin):
        """ Rename a BEL source from one pin name to another.

        new_bel_pin may be a mask'd source BEL pin.

        """
        self.move_source(bel, old_bel_pin, bel, new_bel_pin)

    def move_source(self, old_bel, old_bel_pin, new_bel, new_bel_pin):
        """ Moves source from one BEL in site to another BEL in site.

        new_bel_pin may be a mask'd source BEL pin.

        """
        assert old_bel_pin in old_bel.connections
        assert new_bel_pin not in new_bel.connections

        source = old_bel.connections[old_bel_pin]
        a_bel, a_bel_pin = self.sources[source]
        assert a_bel is old_bel
        assert a_bel_pin == old_bel_pin

        self.sources[source] = (new_bel, new_bel_pin)

    def add_output_from_internal(self, source, internal_source, site_pips=[]):
        """ Adds a source from a site internal source.

        This is used to convert an internal_source wire to a site source.

        source (str): The exact site pin name for this source.  The name must
            identically match the site pin name, or an error will be generated
            when Site.integrate_site is invoked.
        internal_source (str): The internal_source must match the internal
            source name provided to Site.add_internal_source earlier.
        site_pips (list): List of site routing tuples used to connect internal
            source to site pin.

        """
        assert source not in self.sources, source
        assert internal_source in self.internal_sources, internal_source
        assert internal_source in self.internal_source_bel_pins, internal_source

        self.outputs[source] = internal_source
        self.sources[source] = self.internal_sources[internal_source]
        self.site_type_pins[source] = source

        self.link_site_routing(
            [self.internal_source_bel_pins[internal_source]] + site_pips +
            [('bel_pin', source, source, 'input'), ('site_pin', source)])

    def add_output_from_output(self, source, other_source):
        """ Adds an output wire from an existing source wire.

        The new output wire is not a source, but will participate in routing
        formation.

        source (str): The exact site pin name for this source.  The name must
            identically match the site pin name, or an error will be generated
            when Site.integrate_site is invoked.
        other_source (str): The name of an existing source generated from add_source.

        """
        assert source not in self.sources
        assert other_source in self.sources
        self.outputs[source] = other_source

    def add_internal_source(self, bel, cell_pin, wire_name, bel_name, bel_pin):
        """ Adds a site internal source.

        Adds an internal source to the site.  This wire will not be used during
        routing formation, but can be connected to other BELs within the site.

        bel (Bel): Bel object
        cell_pin (str): The exact tech library name for the relevant pin.  Can
            be a bus (e.g. A[5]).  The name must identically match the library
            name or an error will occur during synthesis.
        wire_name (str): The name of the site wire.  This wire_name must not
            overlap with a source or sink site pin name.
        bel_name (str): Name of the BEL this cell pin is mapped too.
        bel_pin (str): Name of the BEL pin this cell pin is mapped too.

        """
        bel.connections[cell_pin] = wire_name
        bel.outputs.add(cell_pin)

        assert wire_name not in self.internal_sources, wire_name
        self.internal_sources[wire_name] = (bel, cell_pin)
        self.internal_source_bel_pins[wire_name] = ('bel_pin', bel_name,
                                                    bel_pin, 'output')

        bel.map_bel_pin_to_cell_pin(
            bel_name=bel_name, bel_pin=bel_pin, cell_pin=cell_pin)

    def connect_internal(self,
                         bel,
                         cell_pin,
                         source,
                         bel_name,
                         bel_pin,
                         site_pips=[]):
        """ Connect a BEL pin to an existing internal source.

        bel (Bel): Bel object
        cell_pin (str): The exact tech library name for the relevant pin.  Can
            be a bus (e.g. A[5]).  The name must identically match the library
            name or an error will occur during synthesis.
        source (str): Existing internal source wire added via
            add_internal_source.
        bel_name (str): Name of the BEL this cell pin is mapped too.
        bel_pin (str): Name of the BEL pin this cell pin is mapped too.
        site_pips (list): List of site routing tuples used to connect source
            BEL pin to this BEL pin.

        """
        assert source in self.internal_sources, source
        assert source in self.internal_source_bel_pins, source
        assert cell_pin not in bel.connections
        bel.connections[cell_pin] = source
        bel.map_bel_pin_to_cell_pin(
            bel_name=bel_name, bel_pin=bel_pin, cell_pin=cell_pin)

        self.link_site_routing([self.internal_source_bel_pins[source]] +
                               site_pips + [('bel_pin', bel_name, bel_pin,
                                             'input')])

    def connect_constant(self,
                         bel,
                         cell_pin,
                         bel_name,
                         bel_pin,
                         value,
                         source_bel,
                         source_bel_pin,
                         site_pips=[]):
        """ Connect a BEL pin to an existing internal constant source.

        bel (Bel): Bel object
        cell_pin (str): The exact tech library name for the relevant pin.  Can
            be a bus (e.g. A[5]).  The name must identically match the library
            name or an error will occur during synthesis.
        bel_name (str): Name of the BEL this cell pin is mapped too.
        bel_pin (str): Name of the BEL pin this cell pin is mapped too.
        value (int): Value of constant net being connected.
        source_bel (str): Name of BEL that is supplying the constant.
        source_bel_pin (str): Name of BEL pin that is supplying the constant.
        site_pips (list): List of site routing tuples used to connect source
            BEL pin to this BEL pin.
        """
        assert value in [0, 1]
        assert cell_pin not in bel.connections
        bel.connections[cell_pin] = value
        bel.map_bel_pin_to_cell_pin(
            bel_name=bel_name, bel_pin=bel_pin, cell_pin=cell_pin)

        self.link_site_routing([('bel_pin', source_bel, source_bel_pin,
                                 'site_source')] + site_pips +
                               [('bel_pin', bel_name, bel_pin, 'input')])

    def add_bel(self, bel, name=None):
        """ Adds a BEL to the site.

        All BELs that use the add_sink, add_source, add_internal_source,
        and connect_internal must call add_bel with the relevant BEL.

        bel (Bel): Bel object
        name (str): Optional name to assign to the bel to enable retrival with
            the maybe_get_bel method.  This name is not used for any other
            reason.

        """

        self.bels.append(bel)
        if name is not None:
            assert name not in self.bel_map
            self.bel_map[name] = bel

    def set_post_route_cleanup_function(self, func):
        """ Set callback to be called on this site during routing formation.

        This callback is intended to enable sites that must perform decisions
        based on routed connections.

        func (function): Function that takes two arguments, the parent module
            and the site object to cleanup.

        """
        self.post_route_cleanup = func

    def integrate_site(self, conn, module):
        """ Integrates site so that it can be used with routing formation.

        This method is called automatically by Module.add_site.

        """
        self.check_site()

        prefix = '{}_{}'.format(self.tile, self.site.name)

        site_pin_map = make_site_pin_map(frozenset(self.site.site_pins))

        # Sanity check BEL connections
        for bel in self.bels:
            bel.set_prefix(prefix)
            bel.set_site(self.site.name)

            for wire in bel.connections.values():
                if wire == 0 or wire == 1:
                    continue

                assert (wire in self.sinks) or (wire in self.sources) or (
                    wire in self.internal_sources
                ) or module.is_top_level(wire), wire

        wires = set()
        unrouted_sinks = set()
        unrouted_sources = set()
        wire_pkey_to_wire = {}
        source_bels = {}
        wire_assigns = {}
        net_map = {}

        for wire in self.internal_sources:
            prefix_wire = prefix + '_' + wire
            wires.add(prefix_wire)

        for wire in self.sinks:
            if wire is module.is_top_level(wire):
                continue

            prefix_wire = prefix + '_' + wire
            wires.add(prefix_wire)
            wire_pkey = get_wire_pkey(conn, self.tile, site_pin_map[wire])
            wire_pkey_to_wire[wire_pkey] = prefix_wire
            self.site_wire_to_wire_pkey[wire] = wire_pkey
            unrouted_sinks.add(wire_pkey)

        for wire in self.sources:
            if wire is module.is_top_level(wire):
                continue

            prefix_wire = prefix + '_' + wire
            wires.add(prefix_wire)
            wire_pkey = get_wire_pkey(conn, self.tile, site_pin_map[wire])

            net_name = module.check_for_net_name(wire_pkey)
            if net_name:
                wires.add(net_name)
                net_map[prefix_wire] = net_name

            wire_pkey_to_wire[wire_pkey] = prefix_wire
            self.site_wire_to_wire_pkey[wire] = wire_pkey
            unrouted_sources.add(wire_pkey)

            source_bel = self.sources[wire]

            if source_bel is not None:
                source_bels[wire_pkey] = source_bel

                if net_name:
                    bel, bel_pin = source_bel
                    bel.add_net_name(bel_pin, net_name)

        shorted_nets = {}

        for source_wire, sink_wire in self.outputs.items():
            wire_source = prefix + '_' + sink_wire
            wire = prefix + '_' + source_wire
            wires.add(wire)
            wire_assigns[wire] = [wire_source]

            # If this is a passthrough wire, then indicate that allow the net
            # is be merged.
            if sink_wire not in site_pin_map:
                continue

            sink_wire_pkey = get_wire_pkey(conn, self.tile,
                                           site_pin_map[sink_wire])
            source_wire_pkey = get_wire_pkey(conn, self.tile,
                                             site_pin_map[source_wire])

            if sink_wire_pkey in unrouted_sinks:
                pip = '{}.{}.{}'.format(self.tile, site_pin_map[source_wire],
                                        site_pin_map[sink_wire])
                shorted_nets[source_wire_pkey] = sink_wire_pkey, pip

                # Because this is being treated as a short, remove the
                # source and sink.
                unrouted_sources.remove(source_wire_pkey)

            if sink_wire_pkey in unrouted_sources:
                pip = '{}.{}.{}'.format(self.tile, site_pin_map[source_wire],
                                        site_pin_map[sink_wire])
                shorted_nets[source_wire_pkey] = sink_wire_pkey, pip

        return dict(
            wires=wires,
            unrouted_sinks=unrouted_sinks,
            unrouted_sources=unrouted_sources,
            wire_pkey_to_wire=wire_pkey_to_wire,
            source_bels=source_bels,
            wire_assigns=wire_assigns,
            shorted_nets=shorted_nets,
            net_map=net_map,
        )

    def check_site(self):
        """ Sanity checks that the site is internally consistent. """
        internal_sources = set(self.internal_sources.keys())
        sinks = set(self.sinks.keys())
        sources = set(self.sources.keys())

        assert len(internal_sources & sinks) == 0, (internal_sources & sinks)
        assert len(internal_sources & sources) == 0, (
            internal_sources & sources)

        bel_ids = set()
        for bel in self.bels:
            bel_ids.add(id(bel))

        for bel_pair in self.sources.values():
            if bel_pair is not None:
                bel, _ = bel_pair
                assert id(bel) in bel_ids

        for sinks in self.sinks.values():
            for bel, _ in sinks:
                assert id(bel) in bel_ids

        for bel_pair in self.internal_sources.values():
            if bel_pair is not None:
                bel, _ = bel_pair
                assert id(bel) in bel_ids

    def maybe_get_bel(self, name):
        """ Returns named BEL from site.

        name (str): Name given during Site.add_bel.

        Returns None if name is not found, otherwise Bel object.
        """
        if name in self.bel_map:
            return self.bel_map[name]
        else:
            return None

    def remove_bel(self, bel_to_remove):
        """ Attempts to remove BEL from site.

        It is an error to remove a BEL if any of its outputs are currently
        in use by the Site.  This method does NOT verify that the sources
        of the BEL are not currently in use.

        """
        bel_idx = None
        for idx, bel in enumerate(self.bels):
            if id(bel) == id(bel_to_remove):
                bel_idx = idx
                break

        assert bel_idx is not None

        # Make sure none of the BEL sources are in use
        for bel in self.bels:
            if id(bel) == id(bel_to_remove):
                continue

            for site_wire in bel.connections.values():
                assert site_wire not in bel_to_remove.outputs, site_wire

        # BEL is not used internal, preceed with removal.
        del self.bels[bel_idx]
        removed_sinks = []
        removed_sources = []

        for sink_wire, bels_using_sink in self.sinks.items():
            bel_idx = None
            for idx, (bel, _) in enumerate(bels_using_sink):
                if id(bel) == id(bel_to_remove):
                    bel_idx = idx
                    break

            if bel_idx is not None:
                del bels_using_sink[bel_idx]

            if len(bels_using_sink) == 0:
                removed_sinks.append(self.site_wire_to_wire_pkey[sink_wire])

        sources_to_remove = []
        for source_wire, (bel, _) in self.sources.items():
            if id(bel) == id(bel_to_remove):
                removed_sources.append(
                    self.site_wire_to_wire_pkey[source_wire])
                sources_to_remove.append(source_wire)

        for wire in sources_to_remove:
            del self.sources[wire]

        return removed_sinks, removed_sources

    def find_internal_source(self, bel, internal_source):
        source_wire = bel.connections[internal_source]
        assert source_wire in self.internal_sources, (internal_source,
                                                      source_wire)

        for source, (bel_source, bel_wire) in self.sources.items():
            if id(bel_source) != id(bel):
                continue

            if bel_wire == internal_source:
                continue

            return source

        return None

    def find_internal_sink(self, bel, internal_sink):
        sink_wire = bel.connections[internal_sink]
        assert sink_wire not in bel.outputs, (internal_sink, sink_wire)

        if sink_wire not in self.internal_sources:
            assert sink_wire in self.sinks
            return sink_wire

    def remove_internal_sink(self, bel, internal_sink):
        sink_wire = self.find_internal_sink(bel, internal_sink)
        bel.connections[internal_sink] = None
        if sink_wire is not None:
            idx_to_remove = []
            for idx, (other_bel,
                      other_internal_sink) in enumerate(self.sinks[sink_wire]):
                if id(bel) == id(other_bel):
                    assert other_internal_sink == internal_sink
                    idx_to_remove.append(idx)

            for idx in sorted(idx_to_remove)[::-1]:
                del self.sinks[sink_wire][idx]

            if len(self.sinks[sink_wire]) == 0:
                del self.sinks[sink_wire]
                return self.site_wire_to_wire_pkey[sink_wire]


@functools.lru_cache(maxsize=None)
def make_site_pin_map(site_pins):
    """ Create map of site pin names to tile wire names. """
    site_pin_map = {}

    for site_pin in site_pins:
        site_pin_map[site_pin.name] = site_pin.wire

    return site_pin_map


def merge_exclusive_sets(set_a, set_b):
    """ set_b into set_a after verifying that set_a and set_b are disjoint. """
    assert len(set_a & set_b) == 0, (set_a & set_b)

    set_a |= set_b


def merge_exclusive_dicts(dict_a, dict_b):
    """ dict_b into dict_a after verifying that dict_a and dict_b have disjoint keys. """
    assert len(set(dict_a.keys()) & set(dict_b.keys())) == 0

    dict_a.update(dict_b)


class WireAssignsBimap():
    """ Bidirectional map of sink wires to source wires modelling wires.

    Provides methods to add and remove assignments to the bimap.

    Supports having multiple sources per sink in the event of ambiguous models.
    Extra sources must be removed before final wire assignments can be
    generated.

    """

    def __init__(self):
        self.sink_to_source_wires = {}
        self.source_to_sink_wires = {}

    def add_wire(self, sink_wire, src_wire):
        """ Add a wire assignment to the bimap.

        Models the verilog:

        assign <sink_wire> = <source_wire>;

        """
        if sink_wire not in self.sink_to_source_wires:
            self.sink_to_source_wires[sink_wire] = set()

        self.sink_to_source_wires[sink_wire].add(src_wire)

        if src_wire not in self.source_to_sink_wires:
            self.source_to_sink_wires[src_wire] = set()

        self.source_to_sink_wires[src_wire].add(sink_wire)

    def yield_wires(self):
        """ Yields (sink, source) pairs.

            AssertionError : If multiple sources are currently defined for
            this sink.
        """
        for sink_wire, source_wires in self.sink_to_source_wires.items():
            assert len(source_wires) == 1, (sink_wire, source_wires)

            yield sink_wire, list(source_wires)[0]

    def is_sink(self, wire):
        """ Is the wire a sink wire? """
        return wire in self.sink_to_source_wires

    def is_source(self, wire):
        """ Is the wire a source wire? """
        return wire in self.source_to_sink_wires

    def get_source_for_sink(self, wire):
        """ Get the root source for a specified sink.

        In the event that the source is also a sink, returns the source of
        that wire, repeated tile the root is found.
        """
        while True:
            if not self.is_sink(wire):
                break

            wires = self.sink_to_source_wires[wire]
            assert len(wires) == 1, wires
            wire = list(wires)[0]

        return wire

    def find_sources_from_sink(self, sink_wire):
        """ Return a set of sources from the sink, empty if there are no sources. """
        if sink_wire not in self.sink_to_source_wires:
            return set()

        return self.sink_to_source_wires[sink_wire]

    def find_sinks_from_source(self, source_wire):
        """ Return a set of sinks from the source, empty if there are no sink. """
        if source_wire not in self.source_to_sink_wires:
            return set()

        return self.source_to_sink_wires[source_wire]

    def remove_source(self, source_wire):
        """ Remove a source from the map.

        Generates an AssertionError if the last source from a sink is removed.

        """
        if source_wire not in self.source_to_sink_wires:
            return

        for sink in self.source_to_sink_wires[source_wire]:
            other_source_wires = self.sink_to_source_wires[sink]
            if len(other_source_wires) == 1:
                assert source_wire not in other_source_wires, source_wire
            else:
                other_source_wires.remove(source_wire)

        del self.source_to_sink_wires[source_wire]

    def remove_sink(self, sink_wire):
        """ Remove a sink from the map. """
        if sink_wire in self.sink_to_source_wires:
            for source_wire in self.sink_to_source_wires[sink_wire]:
                self.source_to_sink_wires[source_wire].remove(sink_wire)

            del self.sink_to_source_wires[sink_wire]

    def merge_wire_assigns_dict(self, wire_assigns_dict):
        """ Add additional wire assigns in the form of a sink to source list map. """
        assert len(
            set(self.sink_to_source_wires.keys()) & set(wire_assigns_dict.
                                                        keys())) == 0
        for sink_wire, source_wires in wire_assigns_dict.items():
            for source_wire in source_wires:
                self.add_wire(sink_wire, source_wire)


class Module(object):
    """ Object to model a design. """

    def __init__(self, db, grid, conn, name="top"):
        self.name = name
        self.db = db
        self.grid = grid
        self.conn = conn
        self.maybe_get_wire = create_maybe_get_wire(conn)
        self.sites = []
        self.source_bels = {}
        self.disabled_drcs = set()
        self.default_iostandard = None
        self.default_drive = None
        self.net_to_iosettings = {}

        # Map of source to sink.
        self.shorted_nets = {}

        # Map of wire_pkey to Verilog wire.
        self.wire_pkey_to_wire = {}

        # wire_pkey of sinks that are not connected to their routing.
        self.unrouted_sinks = set()

        # wire_pkey of sources that are not connected to their routing.
        self.unrouted_sources = set()

        # Known active pips, tuples of sink and source wire_pkey's.
        # The sink wire_pkey is a net with the source wire_pkey.
        self.active_pips = set()

        self.root_in = set()
        self.root_out = set()
        self.root_inout = set()

        self.wires = set()
        self.wire_assigns = WireAssignsBimap()

        # Optional map of site to signal names.
        # This was originally intended for IPAD and OPAD signal naming.
        self.site_to_signal = {}
        self.top_level_signal_nets = set()

        # Optional map of wire_pkey for site pin sources to net name.
        self.wire_pkey_net_map = {}
        self.wire_name_net_map = {}

        # Map of (subckt pin, vector index (None for scale), and net) to
        # .cname value.
        self.cname_map = {}

        # Extra TCL lines (e.g. VREF)
        self.extra_tcl = []

        # IO bank lookup (if part was provided).
        self.iobank_lookup = {}

        # Map of port -> (map of prop -> value).
        self.port_property = {}

    def maybe_add_pip(self, feature):
        parts = feature.split('.')
        assert len(parts) == 3

        sink_wire = self.maybe_get_wire(parts[0], parts[2])
        if sink_wire is None:
            return False

        src_wire = self.maybe_get_wire(parts[0], parts[1])
        if src_wire is None:
            return False

        self.active_pips.add((sink_wire, src_wire, feature))
        return True

    def add_active_pip(self, feature):
        assert self.maybe_add_pip(feature)

    def set_default_iostandard(self, iostandard, drive):
        self.default_iostandard = iostandard
        self.default_drive = drive

    def make_iosettings_map(self, parsed_eblif):
        """
        Fills in the net_to_iosettings dict with IO settings information read
        from the eblif file.
        """

        # Tuple of EBLIF cell parameters.
        IOBUF_PARAMS = (
            "IOSTANDARD",
            "DRIVE",
        )

        # Regex for matching ports belonging to a single inout port
        INOUT_RE = re.compile(
            r"(.*)(_\$inp$|_\$inp(\[[0-9]+\])$|_\$out$|_\$out(\[[0-9]+\])$)(.*)"
        )

        # Eblif parameter decoding
        BIN_RE = re.compile(r"^([01]+)$")
        STR_RE = re.compile(r"^\"(.*)\"$")

        # No subcircuits
        if "subckt" not in parsed_eblif:
            return

        # Look for IO cells
        for subckt in parsed_eblif["subckt"]:

            # No parameters
            if "param" not in subckt:
                continue

            # Gather nets that the cell is connected to.
            # Collapse input and output nets that correspond to an inout port
            # to a single net name
            #
            # "net_$inp" -> "net"
            # "net_$out" -> "net"
            # "net_$inp[0]" -> "net[0]"
            # "net_$out[0]" -> "net[0]"
            nets = set()
            for conn_str in subckt["args"][1:]:
                port, net = conn_str.split("=")

                match = INOUT_RE.match(net)
                if match:
                    groups = match.groups()
                    net = groups[0] + "".join(
                        [g for g in groups[2:] if g is not None])

                nets.add(net)

            # Check if the cell is connected to a top-level port. If not then
            # skip this cell.
            nets &= self.top_level_signal_nets
            if len(nets) == 0:
                continue

            # Get interesting params
            params = {}
            for param, _value in subckt["param"].items():

                if param not in IOBUF_PARAMS:
                    continue

                # Parse the value
                value = _value

                match = BIN_RE.match(_value)
                if match:
                    value = int(match.group(1), 2)

                match = STR_RE.match(_value)
                if match:
                    value = str(match.group(1))

                # Store the parameter
                params[param] = value

            # No interestin params
            if len(params) == 0:
                continue

            # Assign cell parameters to all top-level nets it is connected to.
            for net in nets:
                self.net_to_iosettings[net] = params

    def add_iosettings_from_xdc(self, constraint):
        self.net_to_iosettings[constraint.net] = constraint.params

    def get_site_iosettings(self, site):
        """
        Returns a dict with IO settings for the given site name. The
        information is taken from EBLIF cell parameters, connection between
        top-level ports and EBLIF cells is read from the PCF file.
        """

        # Site not in site to signal list
        if site not in self.site_to_signal:
            return None

        signal = self.site_to_signal[site]

        # Signal not in IO settings map
        if signal not in self.net_to_iosettings:
            return None

        return self.net_to_iosettings[signal]

    def add_port_property(self, port, prop, value):
        """ Add property to port. """
        if port not in self.port_property:
            self.port_property[port] = {}
        self.port_property[port][prop] = value

    def add_extra_tcl_line(self, tcl_line):
        self.extra_tcl.append(tcl_line)

    def disable_drc(self, drc):
        self.disabled_drcs.add(drc)

    def set_net_map(self, net_map):
        self.wire_pkey_net_map = net_map

    def check_for_net_name(self, wire_pkey):
        if wire_pkey in self.wire_pkey_net_map:
            # Top-level port names supress net names.
            name = self.wire_pkey_net_map[wire_pkey]
            if name in self.top_level_signal_nets:
                return None

            return escape_verilog_name(name)
        else:
            return None

    def set_site_to_signal(self, site_to_signal):
        """ Assing site to signal map for top level sites.

        Args:
            site_to_signal (dict): Site to signal name map

        """
        self.site_to_signal = site_to_signal
        self.top_level_signal_nets = set(self.site_to_signal.values())

    def _check_top_name(self, tile, site, name):
        """ Returns top level port name for given tile and site

        Args:
            tile (str): Tile containing site
            site (str): Site containing top level pad.
            name (str): User-defined pad name (e.g. IPAD or OPAD, etc).

        """
        if site not in self.site_to_signal:
            return '{}_{}_{}'.format(tile, site, name)
        else:
            return self.site_to_signal[site]

    def add_top_in_port(self, tile, site, name):
        """ Add a top level input port.

        tile (str): Tile name that will sink the input port.
        site (str): Site name that will sink the input port.
        name (str): Name of port.

        Returns str of root level port name.
        """

        port = self._check_top_name(tile, site, name)
        assert port not in self.root_in
        self.root_in.add(port)

        return port

    def add_top_out_port(self, tile, site, name):
        """ Add a top level output port.

        tile (str): Tile name that will sink the output port.
        site (str): Site name that will sink the output port.
        name (str): Name of port.

        Returns str of root level port name.
        """
        port = self._check_top_name(tile, site, name)
        assert port not in self.root_out
        self.root_out.add(port)

        return port

    def add_top_inout_port(self, tile, site, name):
        """ Add a top level inout port.

        tile (str): Tile name that will sink the inout port.
        site (str): Site name that will sink the inout port.
        name (str): Name of port.

        Returns str of root level port name.
        """
        port = self._check_top_name(tile, site, name)
        assert port not in self.root_inout
        self.root_inout.add(port)

        return port

    def is_top_level(self, wire):
        """ Returns true if specified wire is a top level wire. """
        return wire in self.root_in or wire in self.root_out or wire in self.root_inout

    def add_site(self, site):
        """ Adds a site to the module. """
        integrated_site = site.integrate_site(self.conn, self)

        merge_exclusive_sets(self.wires, integrated_site['wires'])
        merge_exclusive_sets(self.unrouted_sinks,
                             integrated_site['unrouted_sinks'])
        merge_exclusive_sets(self.unrouted_sources,
                             integrated_site['unrouted_sources'])

        merge_exclusive_dicts(self.wire_pkey_to_wire,
                              integrated_site['wire_pkey_to_wire'])
        merge_exclusive_dicts(self.source_bels, integrated_site['source_bels'])
        self.wire_assigns.merge_wire_assigns_dict(
            integrated_site['wire_assigns'])
        merge_exclusive_dicts(self.shorted_nets,
                              integrated_site['shorted_nets'])
        merge_exclusive_dicts(self.wire_name_net_map,
                              integrated_site['net_map'])

        self.sites.append(site)

    def make_routes(self, allow_orphan_sinks):
        """ Create nets from top level wires, activie PIPS, sources and sinks.

        Invoke make_routes after all sites and pips have been added.

        allow_orphan_sinks (bool): Controls whether it is an error if a sink
            has no source.

        """
        self.nets = {}
        self.net_map = {}
        for sink_wire, src_wire in make_routes(
                db=self.db,
                conn=self.conn,
                wire_pkey_to_wire=self.wire_pkey_to_wire,
                unrouted_sinks=self.unrouted_sinks,
                unrouted_sources=self.unrouted_sources,
                active_pips=self.active_pips,
                allow_orphan_sinks=allow_orphan_sinks,
                shorted_nets=self.shorted_nets,
                nets=self.nets,
                net_map=self.net_map,
        ):
            self.wire_assigns.add_wire(sink_wire=sink_wire, src_wire=src_wire)

        self.handle_post_route_cleanup()

    def output_verilog(self):
        """ Yields lines of verilog that represent the design in Verilog.

        Invoke output_verilog after invoking make_routes to ensure that
        inter-site connections are made.

        """
        root_module_args = []

        for in_wire, width in make_bus(self.root_in):
            if width is None:
                root_module_args.append('  input ' + in_wire)
            else:
                root_module_args.append('  input [{}:0] {}'.format(
                    width, in_wire))

        for out_wire, width in make_bus(self.root_out):
            if width is None:
                root_module_args.append('  output ' + out_wire)
            else:
                root_module_args.append('  output [{}:0] {}'.format(
                    width, out_wire))

        for inout_wire, width in make_bus(self.root_inout):
            if width is None:
                root_module_args.append('  inout ' + inout_wire)
            else:
                root_module_args.append('  inout [{}:0] {}'.format(
                    width, inout_wire))

        yield 'module {}('.format(self.name)

        yield ',\n'.join(root_module_args)

        yield '  );'

        for wire, width in make_bus(self.wires):
            if width is None:
                yield '  wire [0:0] {};'.format(wire)
            else:
                yield '  wire [{}:0] {};'.format(width, wire)

        for site in self.sites:
            for bel in site.bels:
                bel.make_net_map(top=self, net_map=self.wire_name_net_map)

        for sink_wire, source_wire in self.wire_assigns.yield_wires():
            self.wire_name_net_map[sink_wire] = flatten_wires(
                source_wire, self.wire_assigns, self.wire_name_net_map)

        for site in self.sites:
            for bel in sorted(site.bels, key=lambda bel: bel.priority):
                yield ''
                for line in bel.output_verilog(
                        top=self, net_map=self.wire_name_net_map, indent='  '):
                    yield line

        for lhs, rhs in self.wire_name_net_map.items():
            yield '  assign {} = {};'.format(lhs, rhs)

        yield 'endmodule'

    def output_bel_locations(self):
        """ Yields lines of tcl that will assign set the location of BELs. """
        for bel in sorted(self.get_bels(), key=lambda bel: bel.priority):
            get_cell = "[get_cells *{cell}]".format(
                cell=bel.get_prefixed_name())

            if bel.bel is not None:
                yield """\
set_property BEL {bel} {get_cell}""".format(
                    bel=bel.bel,
                    get_cell=get_cell,
                )

            yield """\
set_property LOC {site} {get_cell}""".format(
                site=bel.site, get_cell=get_cell)

    def output_nets(self):
        """ Yields lines of tcl that will assign the exact routing path for nets.

        Invoke output_nets after invoking make_routes.

        """
        assert len(self.nets) > 0

        for net_wire_pkey, net in self.nets.items():
            if net_wire_pkey == ZERO_NET:
                yield 'set net [get_nets {<const0>}]'
            elif net_wire_pkey == ONE_NET:
                yield 'set net [get_nets {<const1>}]'
            else:
                if net_wire_pkey not in self.source_bels:
                    continue

                if not net.is_net_alive():
                    continue

                bel, pin = self.source_bels[net_wire_pkey]

                yield """
set pin [get_pins *{cell}/{pin}]
set net [get_nets -of_object $pin]""".format(
                    cell=bel.get_prefixed_name(),
                    pin=pin,
                )

            # If the ZERO_NET or ONE_NET is not used, do not emit it.
            fixed_route = list(
                net.make_fixed_route(self.conn, self.wire_pkey_to_wire))
            if ' '.join(fixed_route).replace(' ', '').replace('{}',
                                                              '') == '[list]':
                assert net_wire_pkey in [ZERO_NET, ONE_NET]
                continue

            yield """set route {fixed_route}""".format(
                fixed_route=' '.join(fixed_route))

            # Remove extra {} elements required to construct 1-length lists.
            yield """set_property FIXED_ROUTE $route $net"""

    def output_interchange_nets(self, constant_nets):
        """ Output nets in format suitable for interchange.

        constant_nets : dict
            Map of 0/1 to net names for constants nets (e.g.
            {0: "<const0>", 1: "<const1>"}).

        Yields net_name (str), list of pips

        """
        assert len(self.nets) > 0

        for net_wire_pkey, net in self.nets.items():
            if net_wire_pkey == ZERO_NET:
                net_name = constant_nets[0]
            elif net_wire_pkey == ONE_NET:
                net_name = constant_nets[1]
            else:
                if net_wire_pkey not in self.source_bels:
                    continue

                if not net.is_net_alive():
                    continue

                bel, cell_pin = self.source_bels[net_wire_pkey]
                assert cell_pin in bel.final_net_names, (
                    bel.get_cell(self), bel.module, bel.name, cell_pin,
                    bel.final_net_names.keys())
                net_name = bel.final_net_names[cell_pin]

            out = []
            net.output_pips(out)
            yield net_name, out

    def output_disabled_drcs(self):
        for drc in self.disabled_drcs:
            yield "set_property SEVERITY {{Warning}} [get_drc_checks {}]".format(
                drc)

    def get_bels(self):
        """ Yield a list of Bel objects in the module. """
        for site in self.sites:
            for bel in site.bels:
                yield bel

    def handle_post_route_cleanup(self):
        """ Handle post route clean-up. """
        for site in self.sites:
            if site.post_route_cleanup is not None:
                site.post_route_cleanup(self, site)

        prune_antennas(self.conn, self.nets, self.unrouted_sinks)

    def find_sinks_from_source(self, site, site_wire):
        """ Yields sink wire names from a site wire source. """
        wire_pkey = site.site_wire_to_wire_pkey[site_wire]
        assert wire_pkey in self.nets

        source_wire = self.wire_pkey_to_wire[wire_pkey]

        return self.wire_assigns.find_sinks_from_source(source_wire)

    def find_sources_from_sink(self, site, site_wire):
        """ Return all source wire names from a site wire sink. """
        wire_pkey = site.site_wire_to_wire_pkey[site_wire]
        sink_wire = self.wire_pkey_to_wire[wire_pkey]

        return self.wire_assigns.find_sources_from_sink(sink_wire)

    def find_source_from_sink(self, site, site_wire):
        """ Return source wire name from a site wire sink.

        Raises
        ------
            AssertionError : If multiple sources are currently defined for
            this sink. """
        wire_pkey = site.site_wire_to_wire_pkey[site_wire]
        sink_wire = self.wire_pkey_to_wire[wire_pkey]

        sources = self.wire_assigns.find_sources_from_sink(sink_wire)
        assert len(sources) == 1
        return list(sources)[0]

    def remove_site(self, site):
        site_idx = None
        for idx, a_site in enumerate(self.sites):
            if site is a_site:
                assert site_idx is None
                site_idx = idx

        assert site_idx is not None

        for bel in site.bels:
            self.remove_bel(site, bel)

    def remove_bel(self, site, bel):
        """ Remove a BEL from the module.

        If this is the last use of a site sink, then that wire and wire
        connection is removed.
        """

        removed_sinks, removed_sources = site.remove_bel(bel)

        # Make sure none of the sources are the only source for a net.
        for wire_pkey in removed_sources:
            source_wire = self.wire_pkey_to_wire[wire_pkey]
            self.wire_assigns.remove_source(source_wire)

        # Remove the sources and sinks from the wires, wire assigns, and net
        for wire_pkey in removed_sources:
            self.remove_source(wire_pkey)
        for wire_pkey in removed_sinks:
            self.remove_sink(wire_pkey)

    def remove_source(self, wire_pkey):
        self.unrouted_sources.remove(wire_pkey)
        del self.source_bels[wire_pkey]
        self.wires.remove(self.wire_pkey_to_wire[wire_pkey])

    def remove_sink(self, wire_pkey):
        self.unrouted_sinks.remove(wire_pkey)
        self.wires.remove(self.wire_pkey_to_wire[wire_pkey])
        sink_wire = self.wire_pkey_to_wire[wire_pkey]
        self.wire_assigns.remove_sink(sink_wire)

    def prune_unconnected_ports(self):
        """
        Identifies and removes unconnected top level ports
        """

        # Checks whether a top level port is connected to any bel
        def is_connected_to_bel(port):
            for site in self.sites:
                for bel in site.bels:
                    for bel_pin, conn in bel.connections.items():
                        if conn == port:
                            return True
            return False

        # Check whether a top level port is used in assign
        def is_used(port):
            if self.wire_assigns.is_sink(port):
                return True
            if self.wire_assigns.is_source(port):
                return True

            return False

        # Remove
        for ports in (self.root_in, self.root_out, self.root_inout):
            to_remove = set()
            for port in ports:
                if not is_connected_to_bel(port) and not is_used(port):
                    to_remove.add(port)
            for port in to_remove:
                ports.remove(port)

    def add_to_cname_map(self, parsed_eblif):
        """ Create a map from subckt (pin, index, net) to cnames.

        Arguments
        ---------
        parsed_eblif
            Output from eblif.parse_blif

        """
        """ Example subckt from eblif.parse_blif:

        # > parse_eblif['subckt'][3]
        {'args': ['MUXF6',
                'I0=$abc$6342$auto$blifparse.cc:492:parse_blif$6343.T0',
                'I1=$abc$6342$auto$blifparse.cc:492:parse_blif$6343.T1',
                'O=$abc$6342$auto$dff2dffe.cc:175:make_patterns_logic$1556',
                'S=$abc$6342$new_n472_'],
        'cname': ['$abc$6342$auto$blifparse.cc:492:parse_blif$6343.fpga_mux_0'],
        'data': [],
        'type': 'subckt'}

        """
        for subckt in parsed_eblif['subckt']:
            if 'cname' not in subckt:
                continue

            assert len(subckt['cname']) == 1

            for arg in subckt['args'][1:]:
                port, net = arg.split('=')

                pin, index = pin_to_wire_and_idx(port)

                self.cname_map[(pin, index,
                                escape_verilog_name(net))] = subckt['cname'][0]

    def lookup_cname(self, pin, idx, net):
        return self.cname_map.get((pin, idx, net))

    def output_extra_tcl(self):
        output = list(self.extra_tcl)

        for port in sorted(self.port_property):
            for prop in sorted(self.port_property[port]):
                value = self.port_property[port][prop]
                output.append('set_property {} {} [get_ports {}]'.format(
                    prop, value, port))

        return output

    def set_io_banks(self, iobanks):
        self.iobank_lookup = dict((v, int(k)) for k, v in iobanks.items())

    def find_iobank(self, hclk_ioi3_tile):
        return self.iobank_lookup[hclk_ioi3_tile]


def make_inverter_path(wire, inverted):
    """ Create site pip path through an inverter. """
    if inverted:
        return [('site_pip', '{}INV'.format(wire), '{}_B'.format(wire)),
                ('inverter', '{}INV'.format(wire))]
    else:
        return [('site_pip', '{}INV'.format(wire), wire)]
