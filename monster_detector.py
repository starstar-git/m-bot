# -*- coding: utf-8 -*-
# 冒险岛自动化打怪脚本
# 图像识别模块 - 使用OpenCV进行怪物检测

import cv2
import numpy as np
import os
import sys

# 添加libs目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'libs'))

from PIL import ImageGrab


class MonsterDetector:
    """怪物检测器 - 使用模板匹配"""

    def __init__(self, monster_templates_dir='monsters'):
        self.monster_templates_dir = monster_templates_dir
        self.player_templates_dir = 'player'
        self.templates = []
        self.template_names = []
        self.monster_groups = {}
        
        # 玩家模板缓存
        self.player_templates_cache = []  # [(template, name), ...]
        self._player_cache_loaded = False
        
        # 玩家位置跟踪
        self.last_player_pos = None
        self.player_pos_history = []
        self.max_history = 5
        self.player_lost_count = 0  # 连续未检测到玩家计数
        
        # 加载模板
        self.load_templates()
        self.load_player_templates()

    def _flip_image(self, img):
        """水平翻转图像（生成左右方向图片）"""
        return cv2.flip(img, 1)

    def _save_with_flip(self, img, save_path):
        """保存原始图片和翻转后的图片"""
        # 保存原始图片
        cv2.imwrite(save_path, img)
        
        # 生成并保存翻转后的图片
        flipped_img = self._flip_image(img)
        dir_name = os.path.dirname(save_path)
        file_name = os.path.basename(save_path)
        name, ext = os.path.splitext(file_name)
        flipped_name = f"{name}_flip{ext}"
        flipped_path = os.path.join(dir_name, flipped_name)
        cv2.imwrite(flipped_path, flipped_img)
        return flipped_path

    def load_templates(self):
        """加载怪物模板图片（支持图片组）"""
        if not os.path.exists(self.monster_templates_dir):
            os.makedirs(self.monster_templates_dir)
            print(f"创建怪物图片目录: {self.monster_templates_dir}")
            print("请将怪物图片放入该目录，或创建子目录作为怪物组")
            return

        self.templates = []
        self.template_names = []
        self.monster_groups = {}

        for entry in os.listdir(self.monster_templates_dir):
            entry_path = os.path.join(self.monster_templates_dir, entry)
            
            if os.path.isdir(entry_path):
                group_name = entry
                group_templates = []
                group_names = []
                
                for filename in os.listdir(entry_path):
                    if filename.endswith('.png') or filename.endswith('.jpg'):
                        if '_flip' in filename:
                            continue
                        path = os.path.join(entry_path, filename)
                        template = cv2.imread(path)
                        if template is not None:
                            self.templates.append(template)
                            template_full_name = f"{group_name}/{filename}"
                            self.template_names.append(template_full_name)
                            group_templates.append(template)
                            group_names.append(filename)
                            print(f"加载怪物模板: {template_full_name}")
                            
                            flipped_path = os.path.join(entry_path, f"{os.path.splitext(filename)[0]}_flip{os.path.splitext(filename)[1]}")
                            if os.path.exists(flipped_path):
                                flipped_template = cv2.imread(flipped_path)
                                if flipped_template is not None:
                                    self.templates.append(flipped_template)
                                    flipped_full_name = f"{group_name}/{os.path.basename(flipped_path)}"
                                    self.template_names.append(flipped_full_name)
                                    group_templates.append(flipped_template)
                                    group_names.append(os.path.basename(flipped_path))
                                    print(f"加载怪物模板: {flipped_full_name}")
                
                if group_templates:
                    self.monster_groups[group_name] = {
                        'templates': group_templates,
                        'names': group_names
                    }
                    print(f"怪物组 [{group_name}] 加载完成，共 {len(group_templates)} 张图片")
            
            elif entry.endswith('.png') or entry.endswith('.jpg'):
                if '_flip' in entry:
                    continue
                path = entry_path
                template = cv2.imread(path)
                if template is not None:
                    self.templates.append(template)
                    self.template_names.append(entry)
                    print(f"加载怪物模板: {entry}")
                    
                    flipped_name = f"{os.path.splitext(entry)[0]}_flip{os.path.splitext(entry)[1]}"
                    flipped_path = os.path.join(self.monster_templates_dir, flipped_name)
                    if os.path.exists(flipped_path):
                        flipped_template = cv2.imread(flipped_path)
                        if flipped_template is not None:
                            self.templates.append(flipped_template)
                            self.template_names.append(flipped_name)
                            print(f"加载怪物模板: {flipped_name}")

        print(f"\n共加载 {len(self.templates)} 个怪物模板")
        print(f"共加载 {len(self.monster_groups)} 个怪物组")

    def capture_screen(self, region=None):
        """截取屏幕"""
        if region:
            screenshot = ImageGrab.grab(bbox=region)
        else:
            screenshot = ImageGrab.grab()

        img = np.array(screenshot)
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
        return img

    def detect_monsters(self, threshold=0.7, region=None):
        """检测屏幕中的怪物（带去重逻辑）"""
        screen = self.capture_screen(region)
        detected = []

        for i, template in enumerate(self.templates):
            result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
            locations = np.where(result >= threshold)

            for pt in zip(*locations[::-1]):
                h, w = template.shape[:2]
                center_x = pt[0] + w // 2
                center_y = pt[1] + h // 2

                template_name = self.template_names[i]
                if '/' in template_name:
                    group_name = template_name.split('/')[0]
                else:
                    group_name = 'unknown'

                detected.append({
                    'name': template_name,
                    'group': group_name,
                    'position': (center_x, center_y),
                    'confidence': result[pt[1], pt[0]],
                    'bbox': (pt[0], pt[1], pt[0] + w, pt[1] + h),
                    'template_size': (w, h)
                })

        detected.sort(key=lambda x: x['confidence'], reverse=True)
        
        # 去重：合并距离相近的检测结果（同一个怪物可能被多个模板匹配）
        return self._remove_duplicates(detected)
    
    def _remove_duplicates(self, detected, overlap_threshold=0.5):
        """去除重复检测结果（基于边界框重叠判断）"""
        if not detected:
            return detected
        
        unique = []
        for monster in detected:
            is_duplicate = False
            mx1, my1, mx2, my2 = monster['bbox']
            
            for existing in unique:
                ex1, ey1, ex2, ey2 = existing['bbox']
                
                # 计算重叠区域
                overlap_x1 = max(mx1, ex1)
                overlap_y1 = max(my1, ey1)
                overlap_x2 = min(mx2, ex2)
                overlap_y2 = min(my2, ey2)
                
                # 计算重叠面积
                if overlap_x2 > overlap_x1 and overlap_y2 > overlap_y1:
                    overlap_area = (overlap_x2 - overlap_x1) * (overlap_y2 - overlap_y1)
                    monster_area = (mx2 - mx1) * (my2 - my1)
                    
                    # 如果重叠面积超过阈值，视为重复
                    if overlap_area / monster_area > overlap_threshold:
                        is_duplicate = True
                        # 如果新检测的置信度更高，替换旧的（保留bbox不变）
                        if monster['confidence'] > existing['confidence']:
                            existing['name'] = monster['name']
                            existing['group'] = monster['group']
                            existing['position'] = monster['position']
                            existing['confidence'] = monster['confidence']
                            existing['template_size'] = monster.get('template_size')
                        break
            
            if not is_duplicate:
                unique.append(monster)
        
        return unique

    def detect_monsters_by_group(self, threshold=0.7, region=None):
        """按怪物组检测，合并同组结果"""
        screen = self.capture_screen(region)
        detected_by_group = {}

        if self.monster_groups:
            for group_name, group_data in self.monster_groups.items():
                group_detected = []
                
                for i, template in enumerate(group_data['templates']):
                    result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
                    locations = np.where(result >= threshold)

                    for pt in zip(*locations[::-1]):
                        h, w = template.shape[:2]
                        center_x = pt[0] + w // 2
                        center_y = pt[1] + h // 2

                        group_detected.append({
                            'name': f"{group_name}/{group_data['names'][i]}",
                            'group': group_name,
                            'position': (center_x, center_y),
                            'confidence': result[pt[1], pt[0]],
                            'bbox': (pt[0], pt[1], pt[0] + w, pt[1] + h)
                        })
                
                if group_detected:
                    group_detected.sort(key=lambda x: x['confidence'], reverse=True)
                    detected_by_group[group_name] = group_detected
        else:
            detected = self.detect_monsters(threshold, region)
            for monster in detected:
                group_name = monster.get('group', 'unknown')
                if group_name not in detected_by_group:
                    detected_by_group[group_name] = []
                detected_by_group[group_name].append(monster)

        return detected_by_group

    def find_nearest_monster(self, player_pos, detected_monsters, y_tolerance=50):
        """找到最近的怪物（考虑Y轴高度限制）"""
        if not detected_monsters:
            return None

        nearest = None
        min_distance = float('inf')

        px, py = player_pos

        for monster in detected_monsters:
            mx, my = monster['position']
            
            if abs(my - py) > y_tolerance:
                continue

            distance = ((mx - px) ** 2 + (my - py) ** 2) ** 0.5

            if distance < min_distance:
                min_distance = distance
                # 创建副本避免修改原始数据
                nearest = dict(monster)
                nearest['distance'] = distance

        return nearest

    def load_player_templates(self):
        """加载玩家模板到内存缓存（启动时加载一次）"""
        self.player_templates_cache = []
        self._player_cache_loaded = False
        
        if not os.path.exists(self.player_templates_dir):
            return
        
        for filename in os.listdir(self.player_templates_dir):
            if filename.endswith('.png') or filename.endswith('.jpg'):
                if '_flip' in filename:
                    continue
                path = os.path.join(self.player_templates_dir, filename)
                template = cv2.imread(path)
                if template is not None:
                    self.player_templates_cache.append((template, filename))
                    print(f"加载玩家模板: {filename}")
                
                # 加载翻转模板
                flipped_path = os.path.join(self.player_templates_dir, f"{os.path.splitext(filename)[0]}_flip{os.path.splitext(filename)[1]}")
                if os.path.exists(flipped_path):
                    flipped_template = cv2.imread(flipped_path)
                    if flipped_template is not None:
                        self.player_templates_cache.append((flipped_template, os.path.basename(flipped_path)))
                        print(f"加载玩家模板: {os.path.basename(flipped_path)}")
        
        self._player_cache_loaded = True
        print(f"共加载 {len(self.player_templates_cache)} 个玩家模板")

    def detect_player_by_name(self, player_name, threshold=0.7, region=None):
        """通过玩家名字图片模板匹配检测玩家位置（使用内存缓存）"""
        if not os.path.exists(self.player_templates_dir):
            print("请添加玩家图片到 player 目录")
            return None

        # 确保缓存已加载
        if not self._player_cache_loaded:
            self.load_player_templates()
        
        if not self.player_templates_cache:
            print("player目录中没有找到图片模板")
            return None

        screen = self.capture_screen(region)
        
        player_positions = []
        
        for template, template_name in self.player_templates_cache:
            result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
            locations = np.where(result >= threshold)

            for pt in zip(*locations[::-1]):
                h, w = template.shape[:2]
                center_x = pt[0] + w // 2
                center_y = pt[1] + h // 2

                player_positions.append({
                    'position': (center_x, center_y),
                    'confidence': result[pt[1], pt[0]],
                    'bbox': (pt[0], pt[1], pt[0] + w, pt[1] + h),
                    'template': template_name
                })

        if player_positions:
            player_positions.sort(key=lambda x: x['confidence'], reverse=True)
            
            if self.last_player_pos:
                px, py = self.last_player_pos
                min_distance = float('inf')
                best_match = None
                
                for pos in player_positions[:5]:
                    dx = pos['position'][0] - px
                    dy = pos['position'][1] - py
                    distance = (dx ** 2 + dy ** 2) ** 0.5
                    
                    if distance < 200 and distance < min_distance:
                        min_distance = distance
                        best_match = pos
                
                if best_match:
                    self.player_lost_count = 0
                    self.update_player_history(best_match['position'])
                    return best_match
            
            self.player_lost_count = 0
            self.update_player_history(player_positions[0]['position'])
            return player_positions[0]
        
        # 模板匹配未检测到玩家，递增丢失计数
        self.player_lost_count += 1
        return None

    def update_player_history(self, pos):
        """更新玩家位置历史"""
        pos = (int(pos[0]), int(pos[1]))
        self.player_pos_history.append(pos)
        if len(self.player_pos_history) > self.max_history:
            self.player_pos_history.pop(0)
        self.last_player_pos = pos

    def add_player_template(self, image_path, name=None):
        """添加玩家名字模板（同时生成左右方向图片）"""
        player_dir = self.player_templates_dir
        if not os.path.exists(player_dir):
            os.makedirs(player_dir)

        template = cv2.imread(image_path)
        if template is None:
            print(f"无法加载图片: {image_path}")
            return False

        if name is None:
            name = os.path.basename(image_path)

        save_path = os.path.join(player_dir, name)
        
        self._save_with_flip(template, save_path)
        
        print(f"添加玩家模板: {save_path}")
        print(f"添加翻转模板: {save_path.replace(os.path.splitext(name)[0], os.path.splitext(name)[0]+'_flip')}")
        return True

    def add_template(self, image_path, name=None, group_name=None):
        """添加新的怪物模板（同时生成左右方向图片）"""
        template = cv2.imread(image_path)
        if template is None:
            print(f"无法加载图片: {image_path}")
            return False

        if name is None:
            name = os.path.basename(image_path)

        if group_name:
            group_dir = os.path.join(self.monster_templates_dir, group_name)
            if not os.path.exists(group_dir):
                os.makedirs(group_dir)
            save_path = os.path.join(group_dir, name)
            template_full_name = f"{group_name}/{name}"
        else:
            save_path = os.path.join(self.monster_templates_dir, name)
            template_full_name = name

        self._save_with_flip(template, save_path)

        template_name_no_flip = template_full_name
        flipped_name = f"{os.path.splitext(template_full_name)[0]}_flip{os.path.splitext(template_full_name)[1]}"

        self.templates.append(template)
        self.template_names.append(template_name_no_flip)
        
        flipped_template = self._flip_image(template)
        self.templates.append(flipped_template)
        self.template_names.append(flipped_name)
        
        if group_name:
            if group_name not in self.monster_groups:
                self.monster_groups[group_name] = {'templates': [], 'names': []}
            self.monster_groups[group_name]['templates'].append(template)
            self.monster_groups[group_name]['names'].append(name)
            
            self.monster_groups[group_name]['templates'].append(flipped_template)
            flip_name_only = f"{os.path.splitext(name)[0]}_flip{os.path.splitext(name)[1]}"
            self.monster_groups[group_name]['names'].append(flip_name_only)
        
        return True

    def add_template_group(self, group_name, image_paths):
        """添加怪物图片组（同时生成左右方向图片）"""
        group_dir = os.path.join(self.monster_templates_dir, group_name)
        if not os.path.exists(group_dir):
            os.makedirs(group_dir)

        success_count = 0
        for image_path in image_paths:
            if os.path.exists(image_path):
                filename = os.path.basename(image_path)
                template = cv2.imread(image_path)
                if template is not None:
                    save_path = os.path.join(group_dir, filename)
                    self._save_with_flip(template, save_path)
                    
                    template_full_name = f"{group_name}/{filename}"
                    self.templates.append(template)
                    self.template_names.append(template_full_name)
                    
                    flipped_template = self._flip_image(template)
                    flip_name = f"{os.path.splitext(filename)[0]}_flip{os.path.splitext(filename)[1]}"
                    flipped_full_name = f"{group_name}/{flip_name}"
                    self.templates.append(flipped_template)
                    self.template_names.append(flipped_full_name)
                    
                    if group_name not in self.monster_groups:
                        self.monster_groups[group_name] = {'templates': [], 'names': []}
                    self.monster_groups[group_name]['templates'].append(template)
                    self.monster_groups[group_name]['names'].append(filename)
                    self.monster_groups[group_name]['templates'].append(flipped_template)
                    self.monster_groups[group_name]['names'].append(flip_name)
                    
                    print(f"添加怪物模板: {template_full_name}")
                    print(f"添加翻转模板: {flipped_full_name}")
                    success_count += 1
                else:
                    print(f"无法加载图片: {image_path}")
            else:
                print(f"文件不存在: {image_path}")

        return success_count > 0

    def get_group_names(self):
        """获取所有怪物组名称"""
        return list(self.monster_groups.keys())

    def get_group_info(self):
        """获取怪物组信息"""
        info = []
        for group_name, group_data in self.monster_groups.items():
            info.append({
                'name': group_name,
                'count': len(group_data['templates'])
            })
        return info

    def get_player_template_count(self):
        """获取玩家模板数量（包括翻转图片）"""
        player_dir = self.player_templates_dir
        if not os.path.exists(player_dir):
            return 0
        count = 0
        for filename in os.listdir(player_dir):
            if filename.endswith('.png') or filename.endswith('.jpg'):
                count += 1
        return count

    def add_player_group(self, image_paths, group_name=None):
        """导入玩家图片组（同时生成左右方向图片）"""
        player_dir = self.player_templates_dir
        if not os.path.exists(player_dir):
            os.makedirs(player_dir)

        success_count = 0
        for image_path in image_paths:
            if os.path.exists(image_path):
                template = cv2.imread(image_path)
                if template is not None:
                    filename = os.path.basename(image_path)
                    save_path = os.path.join(player_dir, filename)
                    self._save_with_flip(template, save_path)
                    print(f"添加玩家模板: {filename}")
                    print(f"添加翻转模板: {os.path.splitext(filename)[0]}_flip{os.path.splitext(filename)[1]}")
                    success_count += 1
                else:
                    print(f"无法加载图片: {image_path}")
            else:
                print(f"文件不存在: {image_path}")

        return success_count > 0


if __name__ == '__main__':
    detector = MonsterDetector()
    print("\n怪物检测器初始化完成")
    print(f"怪物组信息: {detector.get_group_info()}")
