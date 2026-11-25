"""Translational interface between coincident plate and beam nodes.

PyNite has no multipoint displacement constraints. A zero-length penalty
connector enforces displacement compatibility while transmitting no moments.
Its stiffness is scaled from the plate membrane stiffness, not a ground support.
"""
from __future__ import annotations

from copy import copy

import numpy as np
from Pynite.PhysMember import PhysMember
from Pynite.Spring3D import Spring3D


class PlateTranslationLink(Spring3D):
    def T(self):
        return np.eye(12)

    def ke(self):
        stiffness = np.zeros((12, 12))
        for axis in range(3):
            stiffness[axis, axis] = self.ks
            stiffness[axis + 6, axis + 6] = self.ks
            stiffness[axis, axis + 6] = -self.ks
            stiffness[axis + 6, axis] = -self.ks
        return stiffness


class PlateAwareMember(PhysMember):
    """Keep PyNite's automatic subdivision from reconnecting released plate nodes."""

    def descritize(self):
        model = self.model
        excluded = model._osa_disconnected_plate_nodes
        if not excluded:
            return super().descritize()
        filtered = copy(model)
        filtered.nodes = {
            name: node for name, node in model.nodes.items()
            if name not in excluded or node is self.i_node or node is self.j_node
        }
        self.model = filtered
        try:
            super().descritize()
        finally:
            self.model = model
            for member in self.sub_members.values():
                member.model = model
