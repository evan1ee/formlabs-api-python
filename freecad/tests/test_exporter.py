"""Exporter logic against stand-ins for the FreeCAD objects (FreeCAD itself is not needed)."""
from __future__ import annotations

import pytest

from formlabs_fc import exporter, orientation


class Shape:
    def __init__(self, solids=1, placement=None):
        self.Solids = [object()] * solids
        self.Placement = placement
        self.transforms = []
        self.exported = []

    def isNull(self):
        return False

    def copy(self):
        s = Shape(len(self.Solids), self.Placement)
        s.source = self
        return s

    def transformShape(self, m, copy=False):
        self.transforms.append(m)

    def exportStep(self, path):
        self.exported.append(("step", path))
        open(path, "wb").write(b"step")

    def exportStl(self, path):
        self.exported.append(("stl", path))
        open(path, "wb").write(b"stl")


class Matrix:
    def __init__(self, *a):
        self.A = tuple(a) if a else tuple(float(i == j) for i in range(4) for j in range(4))


class Placement:
    def __init__(self, tx=0.0):
        self.Matrix = Matrix(1, 0, 0, tx, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)


class Obj:
    def __init__(self, name, type_id="Part::Feature", solids=1, visible=True, group=None, out=None, tx=0.0):
        self.Name, self.Label, self.TypeId = name, name + " label", type_id
        self.Visibility = visible
        self.Shape = Shape(solids) if solids is not None else None
        self.Group = group or []
        self.OutList = out or []
        self.InList = []
        self._pl = Placement(tx)

    def getGlobalPlacement(self):
        return self._pl


class Doc:
    Name = "Doc"
    FileName = "C:/cad/asm.FCStd"

    def __init__(self, objs):
        self.Objects = objs


def test_visible_solids_are_collected_and_hidden_are_skipped():
    a, b, hidden = Obj("A"), Obj("B"), Obj("H", visible=False)
    assert [o.Name for o in exporter.collect(Doc([a, b, hidden]), [])] == ["A", "B"]


def test_assembly_container_expands_to_its_parts():
    p1, p2 = Obj("P1"), Obj("P2")
    asm = Obj("Asm", "App::Part", solids=None, group=[p1, p2])
    p1.InList = p2.InList = [asm]
    assert [o.Name for o in exporter.collect(Doc([asm, p1, p2]), [])] == ["P1", "P2"]


def test_cut_inputs_are_not_sent_as_extra_parts():
    base, tool = Obj("Base", visible=False), Obj("Tool", visible=False)
    cut = Obj("Cut", out=[base, tool])
    base.InList = tool.InList = [cut]
    assert [o.Name for o in exporter.collect(Doc([base, tool, cut]), [])] == ["Cut"]


def test_selection_wins_and_includes_hidden():
    a, b = Obj("A"), Obj("B", visible=False)
    assert [o.Name for o in exporter.collect(Doc([a, b]), [b])] == ["B"]


def test_nothing_visible_is_a_readable_error():
    with pytest.raises(ValueError, match="no visible solid"):
        exporter.collect(Doc([Obj("H", visible=False)]), [])


class FakeFC:
    Matrix = Matrix


def test_export_writes_files_and_bakes_the_view(tmp_path):
    objs = [Obj("A", tx=10.0), Obj("B")]
    front = orientation.quaternion_to_matrix(0.7071067811865476, 0, 0, 0.7071067811865476)
    out = exporter.export_objects(Doc(objs), objs, tmp_path, "STEP", "view", front, fc=FakeFC, part=None)
    assert [b.body_id for b in out] == ["A", "B"]
    assert all(b.file.exists() and b.file.suffix == ".step" for b in out)
    assert out[0].transform[0][3] == pytest.approx(10.0)  # global placement carried into the stored transform
    assert out[0].doc_path == "C:/cad/asm.FCStd"
    stl = exporter.export_objects(Doc(objs), objs[:1], tmp_path, "STL", "same", None, fc=FakeFC, part=None)
    assert stl[0].file.suffix == ".stl"


def test_duplicate_names_get_unique_ids(tmp_path):
    a, b = Obj("A"), Obj("A")
    out = exporter.export_objects(Doc([a, b]), [a, b], tmp_path, "STEP", "same", None, fc=FakeFC, part=None)
    assert len({o.body_id for o in out}) == 2
