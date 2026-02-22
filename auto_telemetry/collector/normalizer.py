def normalize(raw: float, raw_min: float, raw_max: float,
              phys_min: float, phys_max: float) -> float:
    """
    Лінійна нормалізація для всіх типів сигналів (ADR-002).

    Для encoder_counter/encoder_frequency:
      raw_min=0, raw_max=PPM, phys_min=0.0, phys_max=1.0
      → phys = raw / PPM  (метри або м/с, лінійна екстраполяція коректна)

    Raises ZeroDivisionError якщо raw_min == raw_max.
    """
    return phys_min + (raw - raw_min) / (raw_max - raw_min) * (phys_max - phys_min)
