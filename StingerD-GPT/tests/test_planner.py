import copy
import json
import math
import unittest
from datetime import datetime, timedelta
from server import planner


class PlannerTests(unittest.TestCase):
    request = {"origin": "student-center", "destination": "klaus", "depart_at": "2026-11-03T09:30:00-05:00"}

    def test_contract_and_numeric_consistency(self):
        trace = planner.plan_trip(self.request)
        self.assertTrue(planner.verify_trace(trace))
        self.assertTrue(trace["verified"])
        for p in [trace["chosen"]] + trace["alternatives"]:
            self.assertAlmostEqual(sum(x["duration_minutes"] for x in p["legs"]), p["duration_minutes"], places=2)
            self.assertLessEqual(p["quantiles"]["p10"], p["quantiles"]["p50"])
            self.assertLessEqual(p["quantiles"]["p50"], p["quantiles"]["p90"])
            self.assertEqual(p["geometry"][0], planner.coords(trace["origin"]))
            self.assertEqual(p["geometry"][-1], planner.coords(trace["destination"]))
        self.assertFalse(trace["chosen"]["uncertainty_calibrated"])

    def test_reproducible_seeded_plans(self):
        a, b = planner.plan_trip(self.request), planner.plan_trip(self.request)
        self.assertEqual(a["chosen"], b["chosen"])
        self.assertEqual(a["id"], b["id"])
        self.assertEqual(a["allowed_numbers"], b["allowed_numbers"])

    def test_preferred_modes(self):
        walk = planner.plan_trip({**self.request, "preferred_mode": "walk"})
        bus = planner.plan_trip({**self.request, "preferred_mode": "bus"})
        self.assertEqual([l["kind"] for l in walk["chosen"]["legs"]], ["walk"])
        self.assertTrue(any(l["kind"] == "ride" for l in bus["chosen"]["legs"]))

    def test_route_direction_does_not_reverse_stop_list(self):
        route = next(r for r in planner.ROUTES if r["name"] == "Red")
        outbound = planner._ride(route, 5, 7)
        reverse = planner._ride(route, 7, 5)
        self.assertGreater(reverse["duration_minutes"], outbound["duration_minutes"])
        self.assertEqual(outbound["from_name"], route["stops"][5]["name"])
        self.assertEqual(outbound["to_name"], route["stops"][7]["name"])
        self.assertGreater(len(reverse["geometry"]), len(outbound["geometry"]))

    def test_stop_map_matching_is_monotone_even_on_retraced_roads(self):
        for route in planner.ROUTES:
            indices = [stop["_index"] for stop in route["stops"]]
            self.assertTrue(all(a <= b for a, b in zip(indices, indices[1:])), route["name"])
            for stop in route["stops"]:
                self.assertLess(planner.haversine(planner.coords(stop), route["line"][stop["_index"]]), 90)

    def test_missed_bus_moves_to_next_crossing(self):
        route = next(r for r in planner.ROUTES if r["name"] == "Gold")
        stop = next(s for s in route["stops"] if len(route["_arrivals"][s["id"]]) >= 2)
        times = route["_arrivals"][stop["id"]]
        first = times[len(times) // 2]
        caught, _ = planner._next_bus(route, stop, first - 30, 0)
        missed, _ = planner._next_bus(route, stop, first + 1, 0)
        self.assertGreaterEqual(caught, first - .1)
        self.assertGreater(missed, first)

    def test_far_horizon_widens_confidence(self):
        near = planner.plan_trip({**self.request, "preferred_mode": "walk"})["chosen"]
        far = planner.plan_trip({**self.request, "preferred_mode": "walk", "horizon_minutes": 90})["chosen"]
        self.assertGreater(far["quantiles"]["p90"] - far["quantiles"]["p10"], near["quantiles"]["p90"] - near["quantiles"]["p10"])
        self.assertIn("check closer", far["confidence_label"])

    def test_social_only_widens_same_transit_candidate(self):
        base = planner.plan_trip({**self.request, "preferred_mode": "bus"})
        social = planner.plan_trip({**self.request, "preferred_mode": "bus", "social_factor": True})
        left = {p["id"]: p for p in [base["chosen"]] + base["alternatives"]}
        right = {p["id"]: p for p in [social["chosen"]] + social["alternatives"]}
        for pid in left.keys() & right.keys():
            a, b = left[pid], right[pid]
            if any(l["kind"] == "ride" for l in a["legs"]):
                self.assertEqual(a["quantiles"]["p50"], b["quantiles"]["p50"])
                self.assertGreaterEqual(b["quantiles"]["p90"], a["quantiles"]["p90"])
                self.assertLessEqual(b["quantiles"]["p10"], a["quantiles"]["p10"])
                self.assertTrue(b["social_applied"])

    def test_arrive_by_search_meets_target(self):
        deadline = "2026-11-03T10:00:00-05:00"
        trace = planner.plan_trip({"origin": "student-center", "destination": "midtown-marta", "arrive_by": deadline})
        p = trace["chosen"]
        self.assertGreaterEqual(p["p_on_time"], .90)
        self.assertLess(datetime.fromisoformat(p["arrival_time"]), datetime.fromisoformat(deadline))
        self.assertTrue(planner.verify_trace(trace))

    def test_fixed_departure_assessment_retains_deadline(self):
        deadline = "2026-11-03T10:00:00-05:00"
        safe = planner.plan_trip({"origin": "student-center", "destination": "klaus", "arrive_by": deadline, "preferred_mode": "walk"})
        late = planner.plan_trip({"origin": "student-center", "destination": "klaus", "arrive_by": deadline,
                                  "evaluate_at": "2026-11-03T09:59:00-05:00", "preferred_mode": "walk"})
        self.assertEqual(late["chosen"]["departure_time"], "2026-11-03T09:59:00-05:00")
        self.assertEqual(late["constraints"]["evaluate_at"], late["chosen"]["departure_time"])
        self.assertEqual(late["constraints"]["arrive_by"], deadline)
        self.assertLess(late["chosen"]["p_on_time"], safe["chosen"]["p_on_time"])
        self.assertTrue(planner.verify_trace(late))
        self.assertTrue(planner.verify_trace(planner.get_trace(late["id"])))

    def test_assessment_requires_deadline_and_no_depart_at(self):
        for body in [{**self.request, "evaluate_at": "2026-11-03T09:59:00-05:00"},
                     {"origin": "klaus", "destination": "kendeda", "evaluate_at": "2026-11-03T09:59:00-05:00"},
                     {"origin": "klaus", "destination": "kendeda", "arrive_by": "2026-11-03T10:00:00-05:00", "evaluate_at": "invalid"}]:
            with self.subTest(body=body), self.assertRaises(ValueError):
                planner.plan_trip(body)

    def test_invalid_inputs(self):
        for patch in [{"walk_speed": float("nan")}, {"walk_speed": True}, {"walk_speed": 0}, {"delay_minutes": -1}, {"origin": "missing"}, {"social_factor": "false"}, {"preferred_mode": "fly"}, {"mode": "live"}, {"arrive_by": "bad"}, {"arrive_by": "2026-11-03T10:00:00-05:00"}, {"origin": {"lat": 90, "lon": 0}}]:
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                planner.plan_trip({**self.request, **patch})

    def test_accessibility_limitation_is_explicit(self):
        trace = planner.plan_trip({**self.request, "avoid_stairs": True})
        self.assertTrue(any("cannot be guaranteed" in w for w in trace["warnings"]))

    def test_blue_is_synthetic(self):
        blue = next(r for r in planner.routes() if r["name"] == "Blue")
        self.assertTrue(blue["synthetic"])

    def test_tampered_totals_are_rejected(self):
        trace = planner.plan_trip(self.request)
        trace["chosen"]["duration_minutes"] += 100
        self.assertFalse(planner.verify_trace(trace))

    def test_cached_trace_is_not_mutated_by_caller(self):
        trace = planner.plan_trip(self.request)
        trace["chosen"]["duration_minutes"] = 900
        cached = planner.get_trace(trace["id"])
        self.assertNotEqual(cached["chosen"]["duration_minutes"], 900)
        self.assertTrue(planner.verify_trace(cached))


if __name__ == "__main__":
    unittest.main()
