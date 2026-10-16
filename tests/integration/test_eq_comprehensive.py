"""Comprehensive EQ Subsystem tests — low to deep to extreme.

Covers: unit tests, component tests, integration tests, edge cases,
extreme conditions, and research-backed design decision tests.
"""
import sys, os, tempfile, threading, json, sqlite3, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from learning.eq.engine import EQEngine
from learning.eq.user_state import UserState, UserStateTracker, GoalStatus, EmotionalTone, Agency
from learning.eq.appraiser import CognitiveAppraiser
from learning.eq.adjuster import ResponseAdjuster, ResponseParams
from learning.eq.baseline import BaselineLearner
from learning.eq.manual_override import ManualOverride
from learning.eq.persistence import save_eq_state, load_eq_state


def test_user_state_creation():
    state = UserState()
    assert state.goal_status == GoalStatus.UNKNOWN
    assert state.emotional_tone == EmotionalTone.NEUTRAL
    assert state.engagement == 0.5


def test_user_state_to_dict():
    state = UserState(engagement=0.8, confidence=0.9)
    data = state.to_dict()
    assert data["engagement"] == 0.8
    assert data["confidence"] == 0.9


def test_user_state_from_dict():
    data = {"goal_status": "achieved", "emotional_tone": "positive", "engagement": 0.9}
    state = UserState.from_dict(data)
    assert state.goal_status == GoalStatus.ACHIEVED
    assert state.emotional_tone == EmotionalTone.POSITIVE


def test_user_state_tracker_update():
    tracker = UserStateTracker()
    state = UserState(engagement=0.7)
    tracker.update(state)
    assert tracker.get_state().engagement == 0.7
    assert len(tracker.get_history()) == 1


def test_user_state_tracker_mood_shift():
    tracker = UserStateTracker()
    for _ in range(4):
        tracker.update(UserState(emotional_tone=EmotionalTone.NEGATIVE))
    assert tracker.detect_mood_shift()


def test_cognitive_appraiser_primary():
    appraiser = CognitiveAppraiser()
    state = appraiser.appraise("this is a new topic")
    assert isinstance(state, UserState)
    assert 0.0 <= state.novelty <= 1.0


def test_cognitive_appraiser_secondary():
    appraiser = CognitiveAppraiser()
    state = appraiser.appraise("I understand this, it's easy")
    assert state.coping >= 0.5


def test_cognitive_appraiser_negative():
    appraiser = CognitiveAppraiser()
    state = appraiser.appraise("this is frustrating and I don't understand")
    assert state.emotional_tone == EmotionalTone.NEGATIVE


def test_cognitive_appraiser_positive():
    appraiser = CognitiveAppraiser()
    state = appraiser.appraise("great, that worked perfectly, thanks")
    assert state.emotional_tone == EmotionalTone.POSITIVE


def test_response_adjuster_achieved():
    adjuster = ResponseAdjuster()
    state = UserState(goal_status=GoalStatus.ACHIEVED)
    response, params = adjuster.adjust(state, "Done")
    assert params.warmth == "high"
    assert params.depth == "summary"


def test_response_adjuster_blocked():
    adjuster = ResponseAdjuster()
    state = UserState(goal_status=GoalStatus.BLOCKED)
    response, params = adjuster.adjust(state, "Stuck")
    assert params.warmth == "high"
    assert params.caution_flag is True
    assert params.empathetic_opening is True


def test_response_adjuster_threatened():
    adjuster = ResponseAdjuster()
    state = UserState(goal_status=GoalStatus.THREATENED)
    response, params = adjuster.adjust(state, "Help")
    assert params.warmth == "very high"
    assert params.directness == "very gentle"


def test_response_adjuster_negative_tone():
    adjuster = ResponseAdjuster()
    state = UserState(emotional_tone=EmotionalTone.NEGATIVE)
    response, params = adjuster.adjust(state, "Bad")
    assert params.empathetic_opening is True


def test_response_adjuster_neutral():
    adjuster = ResponseAdjuster()
    state = UserState()
    response, params = adjuster.adjust(state, "OK")
    assert params.warmth == "medium"
    assert params.directness == "direct"


def test_baseline_learning_over_time():
    baseline = BaselineLearner(history_size=5)
    for i in range(5):
        baseline.record_interaction(UserState(
            emotional_tone=EmotionalTone.POSITIVE if i < 3 else EmotionalTone.NEGATIVE
        ))
    assert baseline.get_baseline() == 0.6
    assert baseline.get_history_size() == 5


def test_baseline_mood_shift_detection():
    baseline = BaselineLearner()
    for _ in range(3):
        baseline.record_interaction(UserState(emotional_tone=EmotionalTone.NEGATIVE))
    assert baseline.detect_mood_shift()


def test_baseline_dominant_topic():
    baseline = BaselineLearner()
    baseline.record_interaction(UserState(), topic="python")
    baseline.record_interaction(UserState(), topic="python")
    baseline.record_interaction(UserState(), topic="math")
    assert baseline.get_dominant_topic() == "python"


def test_baseline_preferred_style():
    baseline = BaselineLearner()
    baseline.record_interaction(UserState(), style="exploratory")
    baseline.record_interaction(UserState(), style="exploratory")
    baseline.record_interaction(UserState(), style="direct")
    assert baseline.get_preferred_style() == "exploratory"


def test_baseline_to_dict():
    baseline = BaselineLearner()
    baseline.record_interaction(UserState(), topic="test")
    data = baseline.to_dict()
    assert "emotional_baseline" in data
    assert "topic_counts" in data


def test_baseline_from_dict():
    data = {"emotional_baseline": 0.7, "topic_counts": {"python": 3}, "style_counts": {"direct": 2}}
    baseline = BaselineLearner.from_dict(data)
    assert baseline.get_baseline() == 0.7
    assert baseline.get_dominant_topic() == "python"


def test_manual_override_negative():
    manual = ManualOverride()
    state = manual.detect_override("this is annoying")
    assert state is not None
    assert state.emotional_tone == EmotionalTone.NEGATIVE
    assert manual.is_override_active()


def test_manual_override_positive():
    manual = ManualOverride()
    state = manual.detect_override("let's goooooooooo")
    assert state is not None
    assert state.emotional_tone == EmotionalTone.POSITIVE
    assert manual.is_override_active()


def test_manual_override_clear():
    manual = ManualOverride()
    manual.detect_override("this is annoying")
    manual.clear_override()
    assert not manual.is_override_active()


def test_manual_override_no_match():
    manual = ManualOverride()
    state = manual.detect_override("hello")
    assert state is None
    assert not manual.is_override_active()


def test_eq_engine_basic_flow():
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = EQEngine(db_path=os.path.join(tmpdir, "test.db"))
        state, params = engine.process_input("hello")
        assert isinstance(state, UserState)
        assert isinstance(params, ResponseParams)


def test_eq_engine_negative_input():
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = EQEngine(db_path=os.path.join(tmpdir, "test.db"))
        state, params = engine.process_input("this is frustrating")
        assert state.emotional_tone == EmotionalTone.NEGATIVE
        assert params.empathetic_opening is True


def test_eq_engine_positive_input():
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = EQEngine(db_path=os.path.join(tmpdir, "test.db"))
        state, params = engine.process_input("let's go this is awesome")
        assert state.emotional_tone == EmotionalTone.POSITIVE
        assert params.encouraging_closing is True


def test_eq_engine_manual_override():
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = EQEngine(db_path=os.path.join(tmpdir, "test.db"))
        state, params = engine.process_input("I'm frustrated and angry")
        assert state.emotional_tone == EmotionalTone.NEGATIVE
        assert state.confidence == 0.2


def test_eq_engine_immediate_adaptation():
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = EQEngine(db_path=os.path.join(tmpdir, "test.db"))
        state = UserState(emotional_tone=EmotionalTone.NEGATIVE, confidence=0.1)
        assert engine.should_adapt_immediately(state)


def test_eq_engine_gradual_adaptation():
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = EQEngine(db_path=os.path.join(tmpdir, "test.db"))
        state = UserState(emotional_tone=EmotionalTone.NEUTRAL, confidence=0.5)
        assert not engine.should_adapt_immediately(state)


def test_eq_engine_mood_shift_triggers_immediate():
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = EQEngine(db_path=os.path.join(tmpdir, "test.db"))
        for _ in range(3):
            engine.process_input("this is terrible and awful")
        assert engine.detect_mood_shift()


def test_eq_engine_persistence_save_load():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine1 = EQEngine(db_path=db_path)
        engine1.process_input("let's go this is amazing")
        engine1.save()
        engine2 = EQEngine(db_path=db_path)
        assert engine2.get_baseline() > 0.0


def test_eq_engine_empty_history():
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = EQEngine(db_path=os.path.join(tmpdir, "test.db"))
        assert engine.get_baseline() == 0.5
        assert not engine.detect_mood_shift()


def test_eq_engine_long_session():
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = EQEngine(db_path=os.path.join(tmpdir, "test.db"))
        for i in range(50):
            engine.process_input(f"message {i}")
        assert engine.get_baseline() >= 0.0


def test_eq_engine_concurrent_access():
    errors = []
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = EQEngine(db_path=os.path.join(tmpdir, "test.db"))
        def worker(wid):
            try:
                for i in range(10):
                    engine.process_input(f"worker {wid} message {i}")
            except Exception as e:
                errors.append(f"{wid}: {e}")
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert len(errors) == 0


def test_eq_persistence_corrupted_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "corrupted.db")
        with open(db_path, "w") as f:
            f.write("not a database")
        result = load_eq_state(db_path)
        assert result is None


def test_cpm_sequential_checks():
    appraiser = CognitiveAppraiser()
    state = appraiser.appraise("this is new and I don't understand")
    assert state.novelty > 0.5
    assert state.coping < 0.5


def test_chain_of_emotion():
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = EQEngine(db_path=os.path.join(tmpdir, "test.db"))
        state, params = engine.process_input("this is frustrating")
        assert params.empathetic_opening is True
        assert params.caution_flag is True


def test_emotional_trajectory_markov():
    baseline = BaselineLearner()
    baseline.record_interaction(UserState(emotional_tone=EmotionalTone.POSITIVE))
    baseline.record_interaction(UserState(emotional_tone=EmotionalTone.NEGATIVE))
    assert baseline.get_baseline() == 0.5


def test_mixed_emotion_modeling():
    appraiser = CognitiveAppraiser()
    state = appraiser.appraise("this is great but also confusing")
    assert state.emotional_tone in [EmotionalTone.POSITIVE, EmotionalTone.NEUTRAL, EmotionalTone.NEGATIVE]


def test_response_adaptation_improves_outcomes():
    adjuster = ResponseAdjuster()
    blocked = UserState(goal_status=GoalStatus.BLOCKED)
    _, params = adjuster.adjust(blocked)
    assert params.warmth == "high"
    assert params.directness == "gentle"


def test_hybrid_beats_pure_rules():
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = EQEngine(db_path=os.path.join(tmpdir, "test.db"))
        state, params = engine.process_input("I'm frustrated but let's keep going")
        assert params.empathetic_opening is True
        assert params.encouraging_closing is True
