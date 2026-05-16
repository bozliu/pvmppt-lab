"""PV/MPPT experiment automation toolkit."""

from .presets import REFERENCE_BUCK_BOOST, REFERENCE_PO_CONTROLLER, REFERENCE_TRINA_ARRAY
from .design import ModuleDesignSpec
from .pv import PVModule, PVOperatingPoint

__all__ = [
    "REFERENCE_BUCK_BOOST",
    "REFERENCE_PO_CONTROLLER",
    "REFERENCE_TRINA_ARRAY",
    "ModuleDesignSpec",
    "PVModule",
    "PVOperatingPoint",
]
__version__ = "0.1.0"
