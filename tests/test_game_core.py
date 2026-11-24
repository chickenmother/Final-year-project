"""WS0.1 tests for the task-oriented game core (originally Milestone 1)."""
import json
import tempfile
import unittest
from pathlib import Path

from game.entities import Bot, Bullet
from game.settings import (
    DEFAULT_CONFIG,
    all_fields,
    load_config,
    normalize_config,
    profile_from_config,
    save_config,
)
from game.simulation import Game
from game.workload import get_profile


class GameCoreTests(unittest.TestCase):
    def test_profiles(self):
        self.assertEqual(get_profile("light").bots, 0)
        self.assertGreater(get_profile("medium").obstacles, 0)
        self.assertGreater(get_profile("heavy").bots, get_profile("medium").bots)

    def test_light_initial_state(self):
        game = Game("light", seed=7)
        self.assertEqual(len(game.bots), 0)
        self.assertEqual(len(game.obstacles), 8)
        self.assertEqual(game.player.hp, game.player.max_hp)
        self.assertFalse(game.game_over)

    def test_bullet_damages_obstacle(self):
        game = Game("light", seed=7)
        obstacle = game.obstacles[0]
        bullet = Bullet(obstacle.rect.centerx - 4, obstacle.rect.centery - 8,
                        0, 0, "player", damage=20)
        game.bullets.append(bullet)
        before = obstacle.hp
        game.step("")
        self.assertTrue(obstacle.hp < before or obstacle not in game.obstacles)

    def test_bullet_kills_bot_and_spawns_particles(self):
        game = Game("light", seed=7)
        bot = Bot(game.player.rect.x + 120, game.player.rect.y)
        game.bots.append(bot)
        bullet = Bullet(bot.rect.centerx - 4, bot.rect.centery - 8,
                        0, 0, "player", damage=bot.max_hp)
        game.bullets.append(bullet)
        game.step("")
        self.assertNotIn(bot, game.bots)
        self.assertGreaterEqual(game.score, 100)
        self.assertGreater(len(game.effects), 0)

    def test_player_collision_damages_hp(self):
        game = Game("light", seed=7)
        game.player.hp = 100
        game.player_hit_cooldown = 0.0
        obstacle = game.obstacles[0]
        game.player.rect.center = obstacle.rect.center
        game.step("")
        self.assertLess(game.player.hp, 100)

    def test_snapshot_restore_determinism(self):
        game = Game("light", seed=11)
        script = ["d", "dw", "s", " ", "a", "as", ""] * 5
        for keys in script:
            game.step(keys)
        state = json.loads(json.dumps(game.snapshot()))

        clone = Game("light", seed=999)
        clone.restore(state)
        self.assertEqual(clone.digest(), game.digest())

        for keys in script:
            game.step(keys)
            clone.step(keys)
        self.assertEqual(clone.digest(), game.digest())

    def test_game_over(self):
        game = Game("light", seed=7)
        game.player.hp = 0
        game.step("")
        self.assertTrue(game.game_over)
        self.assertEqual(game.player.hp, 0)

    def test_custom_config_snapshot_restore(self):
        cfg = normalize_config({
            "player": {"max_hp": 77},
            "profiles": {"medium": {"bots": 2, "obstacles": 4}},
        })
        game = Game("medium", seed=11, config=cfg)
        for keys in ("d", "a", " ", "s") * 10:
            game.step(keys)
        state = json.loads(json.dumps(game.snapshot()))
        clone = Game("light", seed=999, config=cfg)
        clone.restore(state)
        self.assertEqual(clone.digest(), game.digest())
        self.assertEqual(clone.player.max_hp, 77)

    def test_render_image_and_jpeg(self):
        game = Game("light", seed=7)
        image = game.render_image((480, 270), smooth=False)
        self.assertEqual(image.size, (480, 270))
        jpg = game.render((480, 270), 40, smooth=False)
        self.assertGreater(len(jpg), 100)
        self.assertEqual(jpg[:2], b"\xff\xd8")


class ConfigTests(unittest.TestCase):
    def test_defaults_are_complete_and_editable(self):
        cfg = normalize_config(None)
        self.assertIn("player", cfg)
        self.assertIn("medium", cfg["profiles"])
        self.assertGreater(len(all_fields("medium")), 20)
        self.assertEqual(normalize_config(DEFAULT_CONFIG)["profiles"]["heavy"]
                         ["bullets_per_second"], 200.0)

    def test_custom_values_reach_game(self):
        cfg = normalize_config({
            "world": {"width": 960, "height": 540},
            "player": {"max_hp": 42, "speed": 11.0},
            "bot": {"max_hp": 77, "speed": 3.5},
            "profiles": {"light": {"bots": 2, "obstacles": 3}},
        })
        game = Game("light", seed=7, config=cfg)
        self.assertEqual(game.player.max_hp, 42)
        self.assertEqual(game.player.hp, 42)
        self.assertEqual(game.player.speed, 11.0)
        self.assertEqual(game.workload.width, 960)
        self.assertEqual(game.workload.height, 540)
        self.assertEqual(len(game.bots), 2)
        self.assertEqual(len(game.obstacles), 3)
        self.assertEqual(game.bots[0].max_hp, 77)

    def test_profile_from_config(self):
        cfg = normalize_config({"profiles": {"medium": {"bots": 12, "obstacles": 33}}})
        profile = profile_from_config(cfg, "medium")
        self.assertEqual(profile.bots, 12)
        self.assertEqual(profile.obstacles, 33)

    def test_save_load_round_trip(self):
        cfg = normalize_config({"player": {"max_hp": 73}})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "game_config.json"
            save_config(cfg, path)
            loaded = load_config(path)
        self.assertEqual(loaded["player"]["max_hp"], 73)
        self.assertEqual(loaded["profiles"]["medium"]["bots"], 5)

    def test_values_are_clamped(self):
        cfg = normalize_config({"player": {"max_hp": 99999, "speed": -4}})
        self.assertEqual(cfg["player"]["max_hp"], 1000)
        self.assertEqual(cfg["player"]["speed"], 1)


class StepSplitTests(unittest.TestCase):
    """WS3.2: A+B (step_ab) and C (step_c) must equal the old fused step()."""

    @staticmethod
    def _script(i):
        keys = "d" if i % 40 < 20 else "a"
        if i % 7 == 0:
            keys += " "
        return keys

    def test_split_matches_fused_step(self):
        fused = Game("medium", seed=11)
        split = Game("medium", seed=11)
        for i in range(600):
            keys = self._script(i)
            fused.step(keys)
            split.step_ab(keys)
            split.step_c()
        self.assertEqual(split.digest(), fused.digest())
        self.assertEqual(split.score, fused.score)
        self.assertEqual(split.deaths, fused.deaths)
        self.assertEqual(split.tick, fused.tick)

    def test_contacts_travel_in_the_snapshot(self):
        game = Game("light", seed=7)
        obstacle = game.obstacles[0]
        game.player.rect.center = obstacle.rect.center
        game.step_ab("")
        self.assertTrue(game.contacts)          # obstacle contact recorded
        remote = Game("light", seed=1)
        remote.restore(json.loads(json.dumps(game.snapshot())))
        self.assertEqual(remote.contacts, game.contacts)
        remote.step_c()
        game.step_c()
        self.assertEqual(remote.digest(), game.digest())

    def test_remote_c_matches_local_c(self):
        """Y steps A+B, X restores and runs C: both must stay identical."""
        local = Game("medium", seed=23)
        remote = Game("medium", seed=99)
        for i in range(400):
            keys = self._script(i)
            local.step_ab(keys)
            remote.restore(json.loads(json.dumps(local.snapshot())),
                           effects=False)
            local.step_c()
            remote.step_c()
            if i % 50 == 0:
                self.assertEqual(remote.digest(), local.digest())
        self.assertEqual(remote.digest(), local.digest())


if __name__ == "__main__":
    unittest.main()
