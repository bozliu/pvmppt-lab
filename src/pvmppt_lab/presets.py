from __future__ import annotations

from dataclasses import asdict, dataclass

from .mppt import POController
from .pv import PVModule


@dataclass(frozen=True)
class PVArrayPreset:
    """Named PV-array preset used by the default reproducible demo."""

    module: PVModule
    series_modules: int
    parallel_strings: int

    @property
    def pmp_ref_w(self) -> float:
        return self.module.pmp_ref_w * self.series_modules * self.parallel_strings

    @property
    def vmp_ref_v(self) -> float:
        return self.module.vmp_ref_v * self.series_modules

    @property
    def imp_ref_a(self) -> float:
        return self.module.imp_ref_a * self.parallel_strings

    @property
    def voc_ref_v(self) -> float:
        return self.module.voc_ref_v * self.series_modules

    @property
    def isc_ref_a(self) -> float:
        return self.module.isc_ref_a * self.parallel_strings

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["array_reference"] = {
            "pmp_ref_w": self.pmp_ref_w,
            "vmp_ref_v": self.vmp_ref_v,
            "imp_ref_a": self.imp_ref_a,
            "voc_ref_v": self.voc_ref_v,
            "isc_ref_a": self.isc_ref_a,
        }
        return payload


@dataclass(frozen=True)
class ReferenceBuckBoostPreset:
    """Open-loop switched buck-boost constants for later fidelity work."""

    dc_source_v: float = 48.0
    mosfet_on_resistance_ohm: float = 0.1
    diode_forward_voltage_v: float = 0.8
    main_pulse_period_s: float = 0.0001
    main_pulse_width_pct: float = 5.0
    complementary_pulse_width_pct: float = 95.0
    inductor_h: float = 0.01e-3
    inductor_series_resistance_ohm: float = 1.0
    capacitor_f: float = 2200e-6
    capacitor_series_resistance_ohm: float = 1.0
    load_resistance_ohm: float = 100.0
    solver_sample_time_s: float = 1e-6

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


REFERENCE_TRINA_ARRAY = PVArrayPreset(
    module=PVModule(),
    series_modules=10,
    parallel_strings=4,
)

REFERENCE_PO_CONTROLLER = POController(
    delta_d=0.001,
    min_duty=0.0,
    max_duty=0.8,
    sample_time_s=1e-4,
    filter_time_constant_s=1e-3,
)

REFERENCE_BUCK_BOOST = ReferenceBuckBoostPreset()
