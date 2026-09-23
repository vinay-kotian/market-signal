"""Supported underlying indices shared by data sources and configuration."""
from typing import Literal, get_args

IndexInstrument = Literal['NIFTY', 'BANKNIFTY', 'SENSEX']
SUPPORTED_INDICES = get_args(IndexInstrument)
