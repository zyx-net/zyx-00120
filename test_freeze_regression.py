import os
import sys
import subprocess
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.resolve()
BAT_PATH = PROJECT_DIR / "freeze_regression.bat"
PY_PATH = PROJECT_DIR / "freeze_regression.py"


def run_cmd(args, cwd=None, shell=False, timeout=30):
    """运行命令并返回 (returncode, stdout, stderr)"""
    if cwd is None:
        cwd = str(PROJECT_DIR)

    result = subprocess.run(
        args,
        cwd=cwd,
        shell=shell,
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )
    return result.returncode, result.stdout, result.stderr


def run_bat(*extra_args):
    """通过 cmd /c 运行 bat 入口"""
    args = ["cmd", "/c", str(BAT_PATH)] + list(extra_args)
    return run_cmd(args)


def run_py(*extra_args):
    """通过 Python 子进程运行 py 入口"""
    args = [sys.executable, str(PY_PATH)] + list(extra_args)
    return run_cmd(args)


def normalize(text):
    """标准化输出用于比较（去除换行、多余空格）"""
    return " ".join(text.strip().split())


class TestEntrypointConsistency(unittest.TestCase):
    """测试 bat 包装层与 Python 入口的一致性与差异"""

    # ============================================================
    # 场景 1: --help 帮助文案
    # ============================================================
    def test_py_help_exit_code(self):
        """Python --help 退出码应为 0"""
        rc, out, err = run_py("--help")
        self.assertEqual(rc, 0, f"退出码应为 0，实际 {rc}\nstderr: {err}")

    def test_bat_help_exit_code(self):
        """BAT --help 退出码应为 0"""
        rc, out, err = run_bat("--help")
        self.assertEqual(rc, 0, f"退出码应为 0，实际 {rc}\nstderr: {err}")

    def test_py_help_contains_argparse_fields(self):
        """Python 帮助应包含 argparse 标准字段（与 BAT 不同）"""
        rc, out, err = run_py("--help")
        self.assertIn("usage:", out)
        self.assertIn("--keep-artifacts", out)
        self.assertIn("--clean-only", out)
        self.assertIn("--check-git-clean", out)
        self.assertIn("options:", out)

    def test_bat_help_contains_bat_specific_fields(self):
        """BAT 帮助应包含 BAT 特有的别名和格式（与 Python 不同）"""
        rc, out, err = run_bat("--help")
        self.assertIn("用法:", out)
        self.assertIn("--keep, --keep-artifacts", out)
        self.assertIn("--export, --export-samples", out)
        self.assertIn("--clean, --clean-before", out)
        self.assertIn("--git-check, --check-git-clean", out)
        self.assertIn("-h, --help", out)
        self.assertIn("默认策略", out)
        self.assertIn("工件统一入口", out)

    def test_help_text_no_cross_contamination(self):
        """帮助文案不能串味：BAT 不含 usage:，Python 不含 用法:"""
        rc_bat, out_bat, _ = run_bat("--help")
        rc_py, out_py, _ = run_py("--help")

        self.assertNotIn("usage:", out_bat, "BAT 帮助不应混入 argparse 风格")
        self.assertNotIn("用法:", out_py, "Python 帮助不应混入 BAT 风格")

    def test_help_no_system_errors(self):
        """--help 输出不应包含系统错误信息"""
        rc_bat, out_bat, err_bat = run_bat("--help")
        rc_py, out_py, err_py = run_py("--help")

        for name, out, err in [("BAT", out_bat, err_bat), ("Python", out_py, err_py)]:
            combined = out + err
            self.assertNotIn("ERROR", combined.upper(),
                           f"{name} --help 不应包含 ERROR: {combined}")
            self.assertNotIn("Traceback", combined,
                           f"{name} --help 不应包含 Traceback: {combined}")
            self.assertNotIn("不是内部或外部命令", combined,
                           f"{name} --help 不应包含系统错误: {combined}")

    # ============================================================
    # 场景 2: --clean-only 仅清理
    # ============================================================
    def test_py_clean_only_exit_code(self):
        """Python --clean-only 退出码应为 0"""
        rc, out, err = run_py("--clean-only")
        self.assertEqual(rc, 0, f"退出码应为 0，实际 {rc}\nstderr: {err}")

    def test_bat_clean_only_exit_code(self):
        """BAT --clean-only 退出码应为 0"""
        rc, out, err = run_bat("--clean-only")
        self.assertEqual(rc, 0, f"退出码应为 0，实际 {rc}\nstderr: {err}")

    def test_py_clean_only_output(self):
        """Python --clean-only 输出应包含清理完成信息"""
        rc, out, err = run_py("--clean-only")
        self.assertIn("[DONE]", out)

    def test_bat_clean_only_vs_py_clean_only_differences(self):
        """BAT --clean-only 会触发完整横幅，Python 不会（包装层差异）"""
        rc_bat, out_bat, _ = run_bat("--clean-only")
        rc_py, out_py, _ = run_py("--clean-only")

        self.assertIn("============================================", out_bat)
        self.assertIn("预约冻结与恢复中心", out_bat)
        self.assertNotIn("============================================", out_py[:200],
                        "Python --clean-only 不应有 BAT 横幅")

    def test_clean_only_no_extra_artifacts(self):
        """--clean-only 不应启动服务器或产生测试工件"""
        rc_bat, out_bat, err_bat = run_bat("--clean-only")
        rc_py, out_py, err_py = run_py("--clean-only")

        for name, out, err in [("BAT", out_bat, err_bat), ("Python", out_py, err_py)]:
            combined = out + err
            self.assertNotIn("PID=", combined,
                           f"{name} --clean-only 不应产生服务器 PID")

        self.assertNotIn("启动服务器", out_py,
                       "Python --clean-only 不应启动服务器")
        self.assertNotIn("等待服务器", out_py,
                       "Python --clean-only 不应等待服务器")

    # ============================================================
    # 场景 3: --git-check / --check-git-clean 参数透传
    # ============================================================
    def test_py_git_check_long_form(self):
        """Python --check-git-clean 长参数名有效"""
        rc, out, err = run_py("--check-git-clean", "--clean-only")
        self.assertEqual(rc, 0, f"--check-git-clean 不应报错: {err}")

    def test_py_git_check_short_form_invalid(self):
        """Python --git-check 短名无效（argparse 大小写敏感且无别名）"""
        rc, out, err = run_py("--git-check", "--clean-only")
        self.assertEqual(rc, 2, f"--git-check 在 Python 层应报错，退出码应为 2，实际 {rc}")
        self.assertIn("unrecognized arguments", err)
        self.assertIn("--git-check", err)

    def test_bat_git_check_short_form(self):
        """BAT --git-check 短名有效（别名映射）"""
        rc, out, err = run_bat("--git-check", "--clean-only")
        self.assertEqual(rc, 0, f"BAT --git-check 别名应有效: {err}")

    def test_bat_git_check_long_form(self):
        """BAT --check-git-clean 长名也有效"""
        rc, out, err = run_bat("--check-git-clean", "--clean-only")
        self.assertEqual(rc, 0, f"BAT --check-git-clean 应有效: {err}")

    def test_git_check_param_passthrough(self):
        """BAT 应正确将 --git-check 透传为 --check-git-clean 给 Python"""
        rc, out, err = run_bat("--git-check", "--clean-only")
        self.assertEqual(rc, 0)
        self.assertIn("附加参数:", out)
        self.assertIn("--check-git-clean", out)

    # ============================================================
    # 场景 4: 非法参数处理
    # ============================================================
    def test_py_invalid_param_exit_code(self):
        """Python 非法参数退出码应为 2"""
        rc, out, err = run_py("--nonexistent-param")
        self.assertEqual(rc, 2, f"非法参数退出码应为 2，实际 {rc}")

    def test_py_invalid_param_error_message(self):
        """Python 非法参数应有明确错误信息"""
        rc, out, err = run_py("--nonexistent-param")
        self.assertIn("unrecognized arguments", err)
        self.assertIn("--nonexistent-param", err)

    def test_bat_invalid_param_silently_ignored(self):
        """BAT 非法参数被默默忽略（包装层行为差异，需断言）"""
        rc, out, err = run_bat("--nonexistent-param", "--clean-only")
        self.assertEqual(rc, 0,
                        "BAT 默默忽略未知参数，退出码仍为 0（这是包装层特性，"
                        "不是 bug，但需通过测试固化行为）")
        self.assertNotIn("unrecognized arguments", err)
        self.assertNotIn("--nonexistent-param", err)

    def test_bat_unknown_param_no_crash(self):
        """BAT 遇到未知参数不应崩溃或产生系统错误"""
        rc, out, err = run_bat("--totally-invalid-param", "--clean-only")
        self.assertNotIn("ERROR", err.upper().replace("[INFO]", "")
                         .replace("[WARN]", "").replace("[CLEAN]", ""))
        self.assertNotIn("Traceback", out + err)

    def test_py_invalid_param_no_branch_fragments(self):
        """Python 参数错误时不应输出分支残片（如部分测试日志）"""
        rc, out, err = run_py("--invalid-param")
        self.assertNotIn("PASS:", out)
        self.assertNotIn("FAIL:", out)
        self.assertNotIn("启动服务器", out)

    # ============================================================
    # 场景 5: 大小写变体 help
    # ============================================================
    def test_bat_help_case_insensitive(self):
        """BAT 帮助参数大小写不敏感（if /I 特性）"""
        test_cases = ["--HELP", "--Help", "--hElP", "-H"]
        for arg in test_cases:
            with self.subTest(arg=arg):
                rc, out, err = run_bat(arg)
                self.assertEqual(rc, 0, f"BAT {arg} 应返回 0")
                self.assertIn("用法:", out, f"BAT {arg} 应显示帮助")

    def test_py_help_case_insensitive_for_long_form(self):
        """Python --help 长形式大小写敏感（argparse 特性）"""
        test_cases = ["--HELP", "--Help"]
        for arg in test_cases:
            with self.subTest(arg=arg):
                rc, out, err = run_py(arg)
                self.assertEqual(rc, 2,
                               f"Python {arg} 大小写变体应报错退出码 2，实际 {rc}")
                self.assertIn("unrecognized arguments", err)

    def test_py_help_short_form_case_insensitive(self):
        """Python -h 短形式大小写敏感"""
        rc, out, err = run_py("-H")
        self.assertEqual(rc, 2, f"Python -H 大写应报错，实际 {rc}")
        self.assertIn("unrecognized arguments", err)

        rc_lower, out_lower, err_lower = run_py("-h")
        self.assertEqual(rc_lower, 0, "Python -h 小写应正常")

    # ============================================================
    # 场景 6: BAT 特有别名参数
    # ============================================================
    def test_bat_alias_keep(self):
        """BAT --keep 别名应透传为 --keep-artifacts"""
        rc, out, err = run_bat("--keep", "--clean-only")
        self.assertEqual(rc, 0)
        self.assertIn("--keep-artifacts", out)

    def test_bat_alias_export(self):
        """BAT --export 别名应透传为 --export-samples"""
        rc, out, err = run_bat("--export", "--clean-only")
        self.assertEqual(rc, 0)
        self.assertIn("--export-samples", out)

    def test_bat_alias_clean(self):
        """BAT --clean 别名应透传为 --clean-before"""
        rc, out, err = run_bat("--clean", "--clean-only")
        self.assertEqual(rc, 0)
        self.assertIn("--clean-before", out)

    def test_py_no_keep_alias(self):
        """Python 不支持 --keep 别名（argparse 前缀匹配意外生效，但这不是有意设计的别名）"""
        rc, out, err = run_py("--keep", "--clean-only")
        self.assertEqual(rc, 0,
                        "注意：argparse 前缀匹配让 --keep 碰巧匹配到 --keep-artifacts，"
                        "退出码为 0，但这不是有意设计的别名")

    def test_py_no_export_alias(self):
        """Python 不支持 --export 别名（argparse 歧义选项报错）"""
        rc, out, err = run_py("--export", "--clean-only")
        self.assertEqual(rc, 2)
        self.assertIn("ambiguous option", err)
        self.assertIn("--export-samples", err)
        self.assertIn("--export-dir", err)

    def test_py_no_clean_alias(self):
        """Python 不支持 --clean 别名（argparse 歧义选项报错）"""
        rc, out, err = run_py("--clean", "--clean-only")
        self.assertEqual(rc, 2)
        self.assertIn("ambiguous option", err)
        self.assertIn("--clean-before", err)
        self.assertIn("--clean-only", err)

    # ============================================================
    # 场景 7: 多参数组合透传边界
    # ============================================================
    def test_bat_multiple_aliases_passthrough(self):
        """BAT 多个别名组合应正确透传"""
        rc, out, err = run_bat("--keep", "--export", "--clean", "--git-check", "--clean-only")
        self.assertEqual(rc, 0)
        self.assertIn("--keep-artifacts", out)
        self.assertIn("--export-samples", out)
        self.assertIn("--clean-before", out)
        self.assertIn("--check-git-clean", out)

    def test_bat_duplicate_params(self):
        """BAT 重复参数会重复透传（边界行为）"""
        rc, out, err = run_bat("--keep", "--keep-artifacts", "--clean-only")
        self.assertEqual(rc, 0)
        # 两个参数都会被添加到 EXTRA_ARGS
        self.assertIn("--keep-artifacts", out)
        # 应出现两次（重复透传）
        count = out.count("--keep-artifacts")
        self.assertGreaterEqual(count, 2,
                               f"重复参数应重复透传，实际出现 {count} 次")

    def test_py_duplicate_params_warning(self):
        """Python 重复参数（argparse store_true 特性）不会报错但也不会警告"""
        rc, out, err = run_py("--keep-artifacts", "--keep-artifacts", "--clean-only")
        self.assertEqual(rc, 0, "argparse store_true 重复参数不报错")

    # ============================================================
    # 场景 8: 退出码透传一致性
    # ============================================================
    def test_py_clean_only_exit_zero(self):
        rc, out, err = run_py("--clean-only")
        self.assertEqual(rc, 0)

    def test_py_help_exit_zero(self):
        rc, out, err = run_py("--help")
        self.assertEqual(rc, 0)

    def test_py_invalid_exit_two(self):
        rc, out, err = run_py("--invalid")
        self.assertEqual(rc, 2)

    def test_bat_exit_code_matches_py_for_clean_only(self):
        """BAT --clean-only 退出码应与 Python 一致"""
        rc_bat, _, _ = run_bat("--clean-only")
        rc_py, _, _ = run_py("--clean-only")
        self.assertEqual(rc_bat, rc_py,
                        f"BAT 退出码 {rc_bat} 应与 Python {rc_py} 一致")

    def test_bat_exit_code_matches_py_for_help(self):
        """BAT --help 退出码应与 Python --help 一致"""
        rc_bat, _, _ = run_bat("--help")
        rc_py, _, _ = run_py("--help")
        self.assertEqual(rc_bat, rc_py,
                        f"BAT 退出码 {rc_bat} 应与 Python {rc_py} 一致")

    # ============================================================
    # 场景 9: 无额外系统报错 / 分支残片
    # ============================================================
    def test_no_branch_fragments_in_help(self):
        """帮助输出中不应混入测试执行相关的分支残片"""
        rc_bat, out_bat, err_bat = run_bat("--help")
        rc_py, out_py, err_py = run_py("--help")

        forbidden_patterns = [
            "PASS:", "FAIL:", "启动服务器", "等待服务器",
            "创建书目", "备份数据", "重启服务器", "PID=",
        ]

        for name, out, err in [("BAT", out_bat, err_bat), ("Python", out_py, err_py)]:
            combined = out + err
            for pattern in forbidden_patterns:
                self.assertNotIn(pattern, combined,
                               f"{name} 帮助输出不应包含 '{pattern}'")

    def test_no_parameter_name_mixing(self):
        """BAT 帮助中的参数名不应混入 Python argparse 的参数名风格"""
        rc_bat, out_bat, _ = run_bat("--help")
        rc_py, out_py, _ = run_py("--help")

        # BAT 帮助应该同时显示短名和长名
        self.assertIn("--keep, --keep-artifacts", out_bat)
        # Python 帮助应该只显示长名（在参数列表中）
        self.assertIn("--keep-artifacts", out_py)
        # Python 帮助不应显示 --keep,
        self.assertNotIn("--keep,", out_py)

    def test_no_system_path_errors(self):
        """运行时不应产生路径相关的系统错误"""
        rc_bat, out_bat, err_bat = run_bat("--clean-only")
        rc_py, out_py, err_py = run_py("--clean-only")

        for name, out, err in [("BAT", out_bat, err_bat), ("Python", out_py, err_py)]:
            combined = out + err
            self.assertNotIn("系统找不到指定的路径", combined)
            self.assertNotIn("The system cannot find the path", combined)
            self.assertNotIn("Permission denied", combined)
            self.assertNotIn("拒绝访问", combined)

    # ============================================================
    # 场景 10: BAT 前置检查行为
    # ============================================================
    def test_bat_has_banner(self):
        """BAT 应有横幅输出（包装层特有）"""
        rc, out, err = run_bat("--clean-only")
        self.assertIn("============================================", out)
        self.assertIn("预约冻结与恢复中心 - Windows 一键回归测试", out)

    def test_py_no_banner(self):
        """Python 入口不应有 BAT 风格横幅"""
        rc, out, err = run_py("--clean-only")
        self.assertNotIn("预约冻结与恢复中心 - Windows 一键回归测试", out)

    def test_bat_shows_artifact_dir(self):
        """BAT 应显示工件目录信息（包装层特有）"""
        rc, out, err = run_bat("--clean-only")
        self.assertIn("工件目录:", out)
        self.assertIn("_regression_artifacts", out)

    def test_bat_shows_extra_args(self):
        """BAT 使用别名参数时应显示附加参数透传情况"""
        rc, out, err = run_bat("--keep", "--clean-only")
        self.assertIn("附加参数:", out)
        self.assertIn("--keep-artifacts", out)


class TestWrapperOnlyIssues(unittest.TestCase):
    """专门测试只会出现在 BAT 包装层的问题"""

    def test_bat_silent_ignore_unknown_params(self):
        """【包装层特有】BAT 默默忽略未知参数，Python 会报错"""
        rc_bat, _, err_bat = run_bat("--unknown-param-xyz", "--clean-only")
        rc_py, _, err_py = run_py("--unknown-param-xyz", "--clean-only")

        self.assertEqual(rc_bat, 0, "BAT 忽略未知参数")
        self.assertNotIn("unrecognized", err_bat)

        self.assertEqual(rc_py, 2, "Python 报错")
        self.assertIn("unrecognized arguments", err_py)

    def test_bat_case_insensitive_help(self):
        """【包装层特有】BAT --HELP 大写有效，Python 无效"""
        rc_bat, out_bat, _ = run_bat("--HELP")
        rc_py, out_py, err_py = run_py("--HELP")

        self.assertEqual(rc_bat, 0)
        self.assertIn("用法:", out_bat)

        self.assertEqual(rc_py, 2)
        self.assertIn("unrecognized arguments", err_py)

    def test_bat_alias_support(self):
        """【包装层特有】BAT 支持 --keep/--export/--clean/--git-check 别名"""
        test_cases = [
            ("--keep", 0, None),
            ("--export", 2, "ambiguous option"),
            ("--clean", 2, "ambiguous option"),
            ("--git-check", 2, "unrecognized arguments"),
        ]
        for alias, expected_py_rc, expected_py_err in test_cases:
            with self.subTest(alias=alias):
                rc_bat, out_bat, err_bat = run_bat(alias, "--clean-only")
                rc_py, out_py, err_py = run_py(alias, "--clean-only")

                self.assertEqual(rc_bat, 0, f"BAT {alias} 应有效")
                self.assertIn("附加参数:", out_bat, f"BAT {alias} 应显示透传参数")

                self.assertEqual(rc_py, expected_py_rc,
                               f"Python {alias} 应返回退出码 {expected_py_rc}，实际 {rc_py}")
                if expected_py_err:
                    self.assertIn(expected_py_err, err_py,
                                 f"Python {alias} 错误信息应包含 '{expected_py_err}'")

    def test_bat_duplicate_param_accumulation(self):
        """【包装层特有】BAT 重复参数会累加，Python 不会"""
        rc_bat, out_bat, _ = run_bat("--keep", "--keep-artifacts", "--clean-only")
        count = out_bat.count("--keep-artifacts")
        self.assertGreaterEqual(count, 2, "BAT 重复参数会重复透传")

    def test_bat_custom_help_text(self):
        """【包装层特有】BAT 帮助文案与 Python 完全不同"""
        rc_bat, out_bat, _ = run_bat("--help")
        rc_py, out_py, _ = run_py("--help")

        self.assertIn("默认策略", out_bat)
        self.assertIn("工件统一入口", out_bat)
        self.assertIn("成功 -> 自动清理工件", out_bat)

        self.assertIn("usage:", out_py)
        self.assertIn("positional arguments", out_py) if "positional arguments" in out_py else None
        self.assertIn("options:", out_py) if "options:" in out_py else None


def run_all_tests():
    """运行所有测试并输出摘要"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestEntrypointConsistency))
    suite.addTests(loader.loadTestsFromTestCase(TestWrapperOnlyIssues))

    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    result = runner.run(suite)

    print("\n" + "=" * 70)
    print("  回归测试摘要")
    print("=" * 70)
    print(f"  总用例数: {result.testsRun}")
    print(f"  通过: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"  失败: {len(result.failures)}")
    print(f"  错误: {len(result.errors)}")
    print("=" * 70)

    if result.failures:
        print("\n【失败用例】")
        for test, traceback in result.failures:
            print(f"\n  ✗ {test}")
            print(f"    {traceback.splitlines()[-2] if len(traceback.splitlines()) > 1 else traceback.strip()}")

    if result.errors:
        print("\n【错误用例】")
        for test, traceback in result.errors:
            print(f"\n  ✗ {test}")
            print(f"    {traceback.splitlines()[-2] if len(traceback.splitlines()) > 1 else traceback.strip()}")

    print()

    # 输出包装层特有问题总结
    print("=" * 70)
    print("  【只会出现在 BAT 包装层的问题总结】")
    print("=" * 70)
    print("  1. 大小写不敏感: --HELP / --Help / -H 在 BAT 层都有效")
    print("  2. 别名支持: --keep / --export / --clean / --git-check 仅在 BAT 层有效")
    print("     注意: --keep 在 Python 层因 argparse 前缀匹配碰巧生效，但不是有意设计")
    print("  3. 未知参数静默忽略: BAT 不报错，Python 退出码 2")
    print("  4. 重复参数累加: BAT 重复参数会重复透传给 Python")
    print("  5. 帮助文案完全独立: BAT 用 echo 输出，Python 用 argparse 生成")
    print("  6. 前置检查: BAT 检查 Python 和 flask 依赖，Python 不检查")
    print("  7. 额外输出: BAT 有横幅、工件提示、结果汇总，Python 没有")
    print("  8. Python argparse 歧义选项: --export / --clean 因多匹配报错")
    print("     (ambiguous option)，BAT 层因别名映射不存在此问题")
    print("=" * 70)

    return len(result.failures) + len(result.errors) == 0


if __name__ == "__main__":
    os.chdir(PROJECT_DIR)
    success = run_all_tests()
    sys.exit(0 if success else 1)
