"""
route_time.engine.physics
=========================
Pod velocity model.

Parameters match Java SimulationSettings:
  acc / decc in G (9.81 m/s²)
  maxVelocityInKMPH → m/s → m/tick

One "tick" = 1 / timeResolutionPerSec seconds.
"""

import math

G = 9.81  # m/s²


class PhysicsModel:
    def __init__(self, settings: dict):
        tps = settings.get("timeResolutionPerSec", 9)
        self.tick_s: float = 1.0 / tps

        acc_g  = settings.get("accInG",  1.0)
        decc_g = settings.get("deccInG", 1.0)
        self.acc_m_s2:  float = acc_g  * G
        self.decc_m_s2: float = decc_g * G

        max_kmph = settings.get("maxVelocityInKMPH", 60)
        self.max_v_m_s: float = max_kmph * 1000 / 3600

        # m per tick at cruise
        self.cruise_m_per_tick: float = self.max_v_m_s * self.tick_s

    def distance_to_reach_speed(self, v_target: float, v_start: float = 0.0) -> float:
        """Metres needed to accelerate from v_start to v_target."""
        if v_target <= v_start:
            return 0.0
        return (v_target ** 2 - v_start ** 2) / (2 * self.acc_m_s2)

    def distance_to_stop(self, v: float) -> float:
        """Metres needed to decelerate from v to 0."""
        if v <= 0:
            return 0.0
        return v ** 2 / (2 * self.decc_m_s2)

    def transit_time_ms(self, distance_m: float, entry_speed: float = 0.0,
                        exit_speed: float = 0.0) -> float:
        """
        Estimate transit time (ms) for a pod travelling distance_m.

        Ramp-up from entry_speed to cruise, cruise, ramp-down to exit_speed.
        If the line is too short for full cruise, solve for the peak speed.
        """
        v_max = self.max_v_m_s
        acc   = self.acc_m_s2
        decc  = self.decc_m_s2

        # distance consumed by acceleration phase
        d_acc = (v_max ** 2 - entry_speed ** 2) / (2 * acc)
        # distance consumed by deceleration phase
        d_decc = (v_max ** 2 - exit_speed ** 2) / (2 * decc)

        if d_acc + d_decc > distance_m:
            # No full-cruise phase — solve for peak speed
            # 0.5*v²/acc + 0.5*v²/decc = distance  →  v² * (1/(2acc) + 1/(2decc)) = dist
            k = 1 / (2 * acc) + 1 / (2 * decc)
            v_peak = math.sqrt(distance_m / k)
            v_peak = min(v_peak, v_max)
            t_acc  = (v_peak - entry_speed) / acc
            t_decc = (v_peak - exit_speed)  / decc
            return (t_acc + t_decc) * 1000

        d_cruise = distance_m - d_acc - d_decc
        t_acc    = (v_max - entry_speed) / acc
        t_cruise = d_cruise / v_max
        t_decc   = (v_max - exit_speed)  / decc
        return (t_acc + t_cruise + t_decc) * 1000
