# 冒险岛自动化打怪脚本
# 键盘模拟模块 - 模拟键盘操作

import sys
import os
import time

# 添加libs目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'libs'))

import pyautogui
from pynput.keyboard import Controller, Key


class KeyboardController:
    """键盘控制器 - 模拟键盘操作"""

    def __init__(self):
        self.keyboard = Controller()
        # 设置安全措施：移动鼠标到角落可终止程序
        pyautogui.FAILSAFE = True
        
        # 特殊按键映射
        self.special_keys = {
            'arrow_left': Key.left,
            'arrow_right': Key.right,
            'arrow_up': Key.up,
            'arrow_down': Key.down,
            'space': Key.space,
            'enter': Key.enter,
            'tab': Key.tab,
            'shift': Key.shift,
            'ctrl': Key.ctrl,
            'alt': Key.alt,
            'backspace': Key.backspace,
            'delete': Key.delete,
            'numpad0': '0',
            'numpad1': '1',
            'numpad2': '2',
            'numpad3': '3',
            'numpad4': '4',
            'numpad5': '5',
            'numpad6': '6',
            'numpad7': '7',
            'numpad8': '8',
            'numpad9': '9',
        }

    def get_key(self, key_str):
        """将字符串键名转换为pynput键对象"""
        if key_str in self.special_keys:
            return self.special_keys[key_str]
        return key_str

    def press_key(self, key, duration=0.1):
        """按下并释放按键"""
        key = self.get_key(key)
        self.keyboard.press(key)
        time.sleep(duration)
        self.keyboard.release(key)

    def hold_key(self, key, duration=1.0):
        """持续按住按键"""
        key = self.get_key(key)
        self.keyboard.press(key)
        time.sleep(duration)
        self.keyboard.release(key)

    # === 持续按键控制（用于连贯移动） ===
    _held_key = None  # 当前持续按住的键

    def hold_key_continuous(self, key):
        """持续按住按键（不释放，直到调用 release_held_key）"""
        mapped = self.get_key(key)
        if self._held_key == mapped:
            return  # 已经在按这个键，无需重复操作
        self.release_held_key()  # 先释放之前的键
        self.keyboard.press(mapped)
        self._held_key = mapped

    def release_held_key(self):
        """释放当前持续按住的键"""
        if self._held_key is not None:
            try:
                self.keyboard.release(self._held_key)
            except Exception:
                pass
            self._held_key = None

    def press_combination(self, keys):
        """组合按键"""
        mapped_keys = [self.get_key(key) for key in keys]
        for key in mapped_keys:
            self.keyboard.press(key)
        time.sleep(0.1)
        for key in mapped_keys:
            self.keyboard.release(key)

    def attack(self, attack_key='j'):
        """普通攻击"""
        self.press_key(attack_key, 0.05)

    def skill_attack(self, skill_key='k'):
        """技能攻击"""
        self.press_key(skill_key, 0.1)

    def jump(self, jump_key='space'):
        """跳跃"""
        self.press_key(jump_key, 0.1)

    def jump_attack(self, jump_key='space', attack_key='j'):
        """跳攻"""
        mapped_jump = self.get_key(jump_key)
        self.keyboard.press(mapped_jump)
        time.sleep(0.15)
        self.press_key(attack_key, 0.05)
        self.keyboard.release(mapped_jump)

    def move_left(self, duration=0.5, key='a'):
        """向左移动"""
        self.hold_key(key, duration)

    def move_right(self, duration=0.5, key='d'):
        """向右移动"""
        self.hold_key(key, duration)

    def move_to_monster(self, player_pos, monster_pos, move_keys=None, attack_distance=100):
        """移动到怪物的攻击距离内"""
        if move_keys is None:
            move_keys = {'left': 'a', 'right': 'd'}
        px, py = player_pos
        mx, my = monster_pos

        # 计算水平距离
        horizontal_dist = mx - px

        # 计算需要移动的距离（停在攻击距离边缘，而非怪物身上）
        if horizontal_dist > 0:
            # 怪物在右边，移动到怪物左边 attack_distance 处
            move_dist = horizontal_dist - attack_distance
        else:
            # 怪物在左边，移动到怪物右边 attack_distance 处
            move_dist = abs(horizontal_dist) - attack_distance

        # 判断移动方向
        if move_dist > 20:  # 还需要靠近
            duration = min(move_dist / 200, 2.0)  # 根据距离调整移动时间
            if horizontal_dist > 0:  # 怪物在右边，向右移动
                self.move_right(duration, move_keys['right'])
                return 'right'
            else:  # 怪物在左边，向左移动
                self.move_left(duration, move_keys['left'])
                return 'left'
        else:
            return 'arrived'  # 已在攻击距离内

    def combo_attack(self, combo_keys=['j', 'j', 'k']):
        """连招攻击"""
        for key in combo_keys:
            self.press_key(key, 0.05)
            time.sleep(0.1)

    def turn_direction(self, player_pos, target_pos, move_keys=None):
        """根据目标位置转身（按下方向键让人物面向目标）"""
        if move_keys is None:
            move_keys = {'left': 'a', 'right': 'd'}
        px = player_pos[0]
        tx = target_pos[0]
        if tx > px:
            # 目标在右边，按右键转身
            self.press_key(move_keys['right'], 0.05)
            return 'right'
        elif tx < px:
            # 目标在左边，按左键转身
            self.press_key(move_keys['left'], 0.05)
            return 'left'
        return 'none'

    def pickup(self, pickup_key='x'):
        """拾取物品"""
        self.press_key(pickup_key, 0.1)

    def skill1_attack(self, skill1_key='l'):
        """技能1攻击"""
        self.press_key(skill1_key, 0.1)


class AttackStrategy:
    """攻击策略 - 根据怪物距离选择攻击方式"""

    def __init__(self, keyboard_controller):
        self.kb = keyboard_controller
        self.attack_count = 0
        self.skill_cooldown = 30  # 技能冷却时间（秒）
        self.last_skill_time = 0   # 上次使用技能的时间
        self.skill1_cooldown = 9999  # 技能1冷却时间（秒），默认9999相当于不自动使用
        self.last_skill1_time = 0  # 上次使用技能1的时间
        self.attack_distance = 100  # 普通攻击距离
        # 按键配置
        self.attack_key = 'j'
        self.skill_key = 'k'
        self.skill1_key = 'l'

    def set_attack_keys(self, attack_key='j', skill_key='k', skill1_key='l'):
        """设置攻击按键"""
        self.attack_key = attack_key
        self.skill_key = skill_key
        self.skill1_key = skill1_key

    def set_attack_distance(self, distance):
        """设置普通攻击距离"""
        self.attack_distance = distance

    def set_skill_cooldown(self, cooldown):
        """设置技能冷却时间（秒）"""
        self.skill_cooldown = cooldown

    def set_skill1_cooldown(self, cooldown):
        """设置技能1冷却时间（秒）"""
        self.skill1_cooldown = cooldown

    def can_use_skill(self):
        """检查技能是否冷却完毕"""
        return time.time() - self.last_skill_time >= self.skill_cooldown

    def can_use_skill1(self):
        """检查技能1是否冷却完毕"""
        return time.time() - self.last_skill1_time >= self.skill1_cooldown

    def try_use_skills(self):
        """独立于怪物检测的技能使用：冷却到就自动释放"""
        current_time = time.time()
        used = False
        if self.can_use_skill():
            self.kb.skill_attack(self.skill_key)
            self.last_skill_time = current_time
            self.attack_count += 1
            used = True
            print(f"[自动技能] 使用技能，冷却时间: {self.skill_cooldown}秒")
        if self.can_use_skill1():
            self.kb.skill1_attack(self.skill1_key)
            self.last_skill1_time = current_time
            self.attack_count += 1
            used = True
            print(f"[自动技能] 使用技能1，冷却时间: {self.skill1_cooldown}秒")
        return used

    def execute_attack(self, distance):
        """根据距离执行普通攻击（技能已由 try_use_skills 独立处理）"""
        if distance < self.attack_distance:
            self.kb.attack(self.attack_key)
            self.attack_count += 1
        else:
            return 'need_move'
        return 'attacked'

    def get_attack_count(self):
        """获取攻击次数"""
        return self.attack_count

    def reset_count(self):
        """重置攻击计数"""
        self.attack_count = 0

    def reset_skill_timers(self):
        """重置技能冷却计时器（设为当前时间，避免启动时立即触发）"""
        self.last_skill_time = time.time()
        self.last_skill1_time = time.time()
        
    def reset_skill_cooldown(self):
        """重置技能冷却"""
        self.last_skill_time = 0


if __name__ == '__main__':
    # 测试代码
    kb = KeyboardController()
    print("键盘控制器初始化完成")
    print("5秒后开始测试攻击...")
    time.sleep(5)
    kb.attack()
    print("攻击完成")