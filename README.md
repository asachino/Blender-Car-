# Blender Car

Blender（4.1）で車の走り・ドリフト・スピン・横転・クラッシュを物理計算してキーフレームに焼き込むアドオンと、
サーキットを自動生成するアドオンです。

| フォルダ | 内容 |
|---|---|
| [car_physics_baker](car_physics_baker/) | **Car Physics Baker**（v1.8.0）。車のモデルとコースのカーブを指定して「焼き込み」すると、走り・サスペンション・ドリフト・スピン・横転・ジャンプ・複数台・タイヤ痕・スモーク・火花・へこみ・パーツ脱落・タイヤバリヤなどをキーフレームにします |
| [inkracer_course_generator](inkracer_course_generator/) | **InkRacer コース自動生成**（v1.2.0）。サーキット・市街地・峠のコース、地形、建物、景観、走行ライン（ベジェ）をまとめて作ります。使い方は [README](inkracer_course_generator/README.md) |
| [demo_scenes](demo_scenes/) | デモ動画のシーンを作るスクリプト（コースや観客席などの飾りも含む）。車のモデルの .blend は含まれません |

## インストール

- **Car Physics Baker**: Blender の「編集 > プリファレンス > アドオン > インストール」で `car_physics_baker/car_physics_baker.py` を選び、有効にします。3D ビューのサイドバー（N）に「Car Physics」タブが出ます。
- **InkRacer コース自動生成**: `inkracer_course_generator` フォルダを ZIP にして（フォルダごと）同じ手順でインストールします。サイドバーに「InkRacer」タブが出ます。

## v1.8.0 の主な変更（Car Physics Baker）

- 段差で車体やタイヤが地面にめり込まない（タイヤの丸みで段差を拾う／車体の底の当たり）
- 横転の後、最後は完全に止まる
- タイヤバリヤを軽く（計算する範囲と期間を絞る）、タイヤを本物のタイヤの形に、飛んだタイヤが地面を抜けない
- スモーク・火花を単色の正三角形に（スモークは白、火花はオレンジ3割・黄色7割）。焼き込み後もモディファイアーの欄で大きさ・量・色を直せる

## デモシーンの作り方

```bash
blender -b <車のモデル.blend> --python demo_scenes/demo_scenes.py -- car_physics_baker/car_physics_baker.py 27_drift_jump out/27_drift_jump.blend
```

車のモデル（R32・テスタロッサ・S2000）を入れた .blend が別に必要です（このリポジトリには含めていません）。
5車種（R32・S2000・F40・カウンタック・テスタロッサ）のタグ付きファイル（シーン「CPB_READY_5車種」）を渡すと、[cars5.py](demo_scenes/cars5.py) で車を拾います（01_chicane_roll・02_spin_barrier・13_jump_roll・14_oval・27_drift_jump で確認済み）。

## タグ付き車両コレクションのセットアップ

複数の車を別ファイルからアペンドしてCPBに登録する場合は、[セットアップスクリプト](car_physics_baker/setup_from_tagged_collections.py)を使えます。CPBアドオンを有効にした後、Blenderのテキストエディターで実行してください。車両コレクションには `rev_car`、車両ターゲットには `rev_role`（`BODY` / `FL` / `FR` / `RL` / `RR`）を設定します。セットアップは軸方向・親・制約・アニメーション・スケールを検査し、古いシーン設定と `cpb_*` 基準姿勢キャッシュをクリアして登録します。

スクリプトが作る80mの直線パスは登録確認専用です。既存の走行コースと地面を設定してから本番ベイクしてください。配置を変える場合は、先にベイクをクリアし、BODYと4輪をまとめて移動してからセットアップを再実行します。検証済みの5車種用モデル資産はライセンス・配布範囲を確認できないため、このリポジトリには含めていません。
