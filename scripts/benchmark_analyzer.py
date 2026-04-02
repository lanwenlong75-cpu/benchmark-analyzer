#!/usr/bin/env python3
"""
Benchmark Analyzer — 对标账号全自动拆解脚本
用法: python3 benchmark_analyzer.py <Excel文件路径> [输出目录]

功能：
1. 读取Excel数据
2. 生成爆款内容体检报告
3. 下载Top10音频
4. 使用 whisper-medium 转写为语料
5. OpenCC 繁简转换 + 基础错别字修正
6. 按博主名存放到对应文件夹
"""

import os
import re
import sys
import subprocess
import argparse
from datetime import datetime
from collections import Counter

try:
    import pandas as pd
    import requests
    import opencc
except ImportError as e:
    print(f"缺少依赖: {e}")
    print("请运行: pip install pandas openpyxl requests opencc-python-reimplemented")
    sys.exit(1)

# ============ 用户配置区域 ============
WHISPER_CLI = "/opt/homebrew/Cellar/whisper-cpp/1.8.3/bin/whisper-cli"
MODEL_PATH = os.path.expanduser("~/whisper-models/ggml-medium.bin")
# 如果 medium 模型不存在，尝试 tiny 回退
FALLBACK_MODEL = os.path.expanduser("~/whisper-models/tiny.bin")
# =======================================


def get_default_output_dir():
    """智能探测输出目录，优先使用当前工作目录"""
    cwd = os.getcwd()
    # 1. 当前目录下有 "对标账号案例库"
    candidate1 = os.path.join(cwd, "对标账号案例库")
    if os.path.exists(candidate1):
        return candidate1
    # 2. 脚本所在目录的父目录下有 "对标账号案例库"
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidate2 = os.path.join(script_dir, "对标账号案例库")
    if os.path.exists(candidate2):
        return candidate2
    # 3. 默认：当前工作目录下新建
    return candidate1


def ensure_model():
    """确保语音模型可用"""
    if os.path.exists(MODEL_PATH):
        return MODEL_PATH
    if os.path.exists(FALLBACK_MODEL):
        print(f"⚠️  medium 模型不存在，回退到 tiny: {FALLBACK_MODEL}")
        return FALLBACK_MODEL
    print("❌ 错误：找不到 whisper 模型文件。")
    print(f"   期望路径: {MODEL_PATH}")
    print("   请下载 medium 模型到该路径:")
    print("   curl -L -o ~/whisper-models/ggml-medium.bin "
          "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.bin")
    sys.exit(1)


def get_author_name(df):
    """从Excel中提取博主名称"""
    for col in ['达人昵称', '作者', 'author', '博主', '昵称', '名称']:
        if col in df.columns:
            vals = df[col].dropna()
            if len(vals) > 0:
                return str(vals.iloc[0]).strip()
    return "未知博主"


def clean_title(title, max_len=55):
    """清理标题中的非法字符，用于文件名"""
    title = re.sub(r'#\w+', '', str(title))
    title = re.sub(r'\s+', ' ', title).strip()
    title = re.sub(r'[<>:"/\\|?*]', '', title)
    return title[:max_len].strip() or "untitled"


def parse_duration(d):
    """解析视频时长为秒数"""
    if pd.isna(d):
        return None
    s = str(d).strip()
    m = re.match(r'(\d+)分(\d+)秒', s)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    m = re.match(r'(\d+)秒', s)
    if m:
        return int(m.group(1))
    return None


def duration_bucket(sec):
    if sec is None:
        return '未知'
    if sec < 30:
        return '<30秒'
    if sec <= 60:
        return '30-60秒'
    if sec <= 120:
        return '1-2分钟'
    if sec <= 300:
        return '2-5分钟'
    if sec <= 600:
        return '5-10分钟'
    return '10分钟+'


def time_bucket(dt):
    if pd.isna(dt):
        return '未知'
    h = dt.hour
    if 0 <= h < 6:
        return '凌晨(0-6点)'
    if 6 <= h < 12:
        return '早上(6-12点)'
    if 12 <= h < 18:
        return '下午(12-18点)'
    return '晚上(18-24点)'


def classify_topic(row):
    """基于标题和标签进行简单主题分类"""
    text = str(row.get('视频描述', '')) + ' ' + str(row.get('视频标签', ''))
    mapping = {
        '创业': '创业/商业', '商业': '创业/商业',
        '赚钱': '赚钱/财富', '财富': '赚钱/财富',
        '社交': '社交/人脉', '人脉': '社交/人脉',
        '认知': '认知/成长', '思维': '认知/成长', '成长': '认知/成长',
        '职场': '职场/技能', '管理': '职场/技能',
        '情感': '情感/心理', '心理': '情感/心理',
    }
    scores = {}
    for kw, topic in mapping.items():
        if kw in text:
            scores[topic] = scores.get(topic, 0) + 1
    return max(scores, key=scores.get) if scores else '其他'


def generate_report(df, author_name, output_dir):
    """生成爆款内容体检报告"""
    report = []
    report.append(f"# 🎯 爆款内容体检报告 - @{author_name}")
    report.append("")

    # 数据概览
    df['发布时间'] = pd.to_datetime(df['发布时间'], errors='coerce')
    time_min, time_max = df['发布时间'].min(), df['发布时间'].max()
    report.append("## 1. 数据概览")
    report.append("")
    report.append("| 指标 | 数值 |")
    report.append("|------|------|")
    report.append(f"| 视频总数 | {len(df)} |")
    if pd.notna(time_min) and pd.notna(time_max):
        report.append(f"| 时间范围 | {time_min.strftime('%Y-%m-%d %H:%M')} ~ {time_max.strftime('%Y-%m-%d %H:%M')} |")
    report.append(f"| 总点赞量 | {int(df['点赞量'].sum()):,} |")
    report.append(f"| 总收藏量 | {int(df['收藏量'].sum()):,} |")
    report.append(f"| 总评论量 | {int(df['评论量'].sum()):,} |")
    report.append(f"| 总分享量 | {int(df['分享量'].sum()):,} |")
    report.append(f"| 平均互动指数 | {int(df['interaction_score'].mean()):,} |")
    report.append("")

    def ranking(title, sort_col, extras):
        report.append(f"## {title}")
        report.append("")
        cols = ['排名', '标题', sort_col] + extras
        report.append("| " + " | ".join(cols) + " |")
        report.append("|" + "|".join(['------'] * len(cols)) + "|")
        top = df.nlargest(10, sort_col)
        for i, (_, row) in enumerate(top.iterrows(), 1):
            t = clean_title(row['视频描述'], max_len=50)
            vals = [f"{int(row[c]):,}" for c in [sort_col] + extras]
            report.append(f"| {i} | {t} | " + " | ".join(vals) + " |")
        report.append("")

    ranking("2. 点赞排行榜 Top 10", '点赞量', ['收藏量', '评论量', '分享量'])
    ranking("3. 收藏排行榜 Top 10", '收藏量', ['点赞量', '评论量', '分享量'])
    ranking("4. 评论排行榜 Top 10", '评论量', ['点赞量', '收藏量', '分享量'])
    ranking("5. 分享排行榜 Top 10", '分享量', ['点赞量', '收藏量', '评论量'])

    # 综合互动榜
    report.append("## 6. 综合互动排行榜 Top 10")
    report.append("")
    report.append("| 排名 | 标题 | 综合互动 | 点赞 | 收藏 | 评论 | 分享 |")
    report.append("|------|------|---------:|-----:|-----:|-----:|-----:|")
    top10 = df.nlargest(10, 'interaction_score')
    for i, (_, row) in enumerate(top10.iterrows(), 1):
        t = clean_title(row['视频描述'], max_len=45)
        report.append(
            f"| {i} | {t} | "
            f"{int(row['interaction_score']):,} | "
            f"{int(row['点赞量']):,} | {int(row['收藏量']):,} | "
            f"{int(row['评论量']):,} | {int(row['分享量']):,} |"
        )
    report.append("")

    # 高频标签
    all_tags = []
    for tags in df['视频标签']:
        if tags and str(tags) not in ('0', '0.0', 'nan'):
            all_tags.extend([t.strip() for t in str(tags).split('、') if t.strip()])
    tag_counts = Counter(all_tags)
    report.append("## 7. 高频标签 Top 20")
    report.append("")
    report.append("| 排名 | 标签 | 出现次数 |")
    report.append("|------|------|---------:|")
    for i, (tag, cnt) in enumerate(tag_counts.most_common(20), 1):
        report.append(f"| {i} | {tag} | {cnt} |")
    report.append("")

    # 主题分布
    topic_counts = df['主题'].value_counts()
    report.append("## 8. 高频主题分布")
    report.append("")
    report.append("| 主题 | 视频数 | 占比 |")
    report.append("|------|-------:|-----:|")
    for topic, cnt in topic_counts.items():
        report.append(f"| {topic} | {cnt} | {cnt/len(df)*100:.1f}% |")
    report.append("")

    # Top20主题分布
    top20_topics = df.nlargest(20, 'interaction_score')['主题'].value_counts()
    report.append("## 9. Top 20 高互动视频的主题分布")
    report.append("")
    report.append("| 主题 | 出现次数 |")
    report.append("|------|---------:|")
    for topic, cnt in top20_topics.items():
        report.append(f"| {topic} | {cnt} |")
    report.append("")

    # 时长分析
    ds = df.groupby('时长区间').agg(平均互动=('interaction_score', 'mean'), 视频数=('interaction_score', 'size')).sort_values('平均互动', ascending=False)
    report.append("## 10. 视频时长分析")
    report.append("")
    report.append("| 时长区间 | 平均互动 | 视频数 |")
    report.append("|----------|---------:|-------:|")
    for b, r in ds.iterrows():
        report.append(f"| {b} | {int(r['平均互动']):,} | {int(r['视频数'])} |")
    report.append("")

    # 发布时间分析
    ts = df.groupby('发布时段').agg(平均互动=('interaction_score', 'mean'), 视频数=('interaction_score', 'size')).sort_values('平均互动', ascending=False)
    report.append("## 11. 发布时间分析")
    report.append("")
    report.append("| 时段 | 平均互动 | 视频数 |")
    report.append("|------|---------:|-------:|")
    for b, r in ts.iterrows():
        report.append(f"| {b} | {int(r['平均互动']):,} | {int(r['视频数'])} |")
    report.append("")

    # 值得深度研究的视频
    def reason(row):
        reasons = []
        if row['分享量'] > df['分享量'].quantile(0.8):
            reasons.append("高分享量 → 有传播性")
        if row['评论量'] > df['评论量'].quantile(0.8):
            reasons.append("高评论量 → 有讨论度")
        if row['收藏量'] > df['收藏量'].quantile(0.8):
            reasons.append("高收藏量 → 有实用价值")
        return " / ".join(reasons) if reasons else "综合互动表现突出"

    report.append("## 12. 值得深度研究的视频 Top 10")
    report.append("")
    report.append("| 排名 | 视频描述 | 推荐理由 |")
    report.append("|------|----------|----------|")
    for i, (_, row) in enumerate(top10.iterrows(), 1):
        report.append(f"| {i} | {clean_title(row['视频描述'], 50)} | {reason(row)} |")
    report.append("")

    # 爆款规律总结
    avg_ia = max(1, int(df['interaction_score'].mean()))
    top10_pct = max(1, int(len(df) * 0.1))
    top10_avg = int(df.nlargest(top10_pct, 'interaction_score')['interaction_score'].mean())
    report.append("## 13. 爆款规律总结")
    report.append("")
    report.append("### 📊 数据洞察")
    report.append("")
    report.append(f"- 平均点赞: {int(df['点赞量'].mean()):,} | 平均收藏: {int(df['收藏量'].mean()):,} | "
                  f"平均分享: {int(df['分享量'].mean()):,} | 平均评论: {int(df['评论量'].mean()):,}")
    report.append(f"- Top 10% 视频的平均互动: {top10_avg:,}（是整体的 {top10_avg/avg_ia:.1f} 倍）")
    report.append("")

    # 高频词
    all_titles_text = ' '.join(df['视频描述'].astype(str).tolist())
    words = [w for w in re.findall(r'[\u4e00-\u9fa5]{2,4}', all_titles_text)
             if w not in {
                 '的', '了', '是', '我', '你', '在', '和', '就', '都', '要', '会', '能',
                 '这', '那', '有', '没', '不', '人', '一个', '可以', '怎么', '什么',
                 '别人', '一定', '最', '更', '那么', '自己', '关系', '老板', '就是',
                 '不要', '还是', '而是', '他们', '我们', '但是', '因为', '所以',
                 '如果', '可能', '其实', '总是'
             }]
    wc = Counter(words)
    report.append("### 🎯 爆款高频词")
    report.append("")
    for w, c in wc.most_common(10):
        report.append(f"- **{w}**: 出现 {c} 次")
    report.append("")

    bd = ds.index[0] if len(ds) > 0 else '未知'
    bt = ts.index[0] if len(ts) > 0 else '未知'
    report.append("### ⏰ 最佳发布时间")
    report.append(f"- {bt} 发布效果最好")
    report.append("")
    report.append("### 📹 最佳视频时长")
    report.append(f"- {bd} 的视频平均互动最高")
    report.append("")
    report.append("### 💡 核心策略建议")
    report.append("")
    report.append(f"1. **内容方向**: 聚焦\"{topic_counts.index[0]}\"主题，这是账号的主力内容方向")
    report.append("2. **传播设计**: 注重提升分享率（分享权重2.5x最高），设计有传播点的内容")
    report.append("3. **收藏价值**: 干货类内容收藏率高，注意沉淀实用信息")
    report.append(f"4. **发布时间**: 优先选择 {bt} 时段发布")
    report.append("")
    report.append("---")
    report.append("")
    report.append(f"*报告生成时间: {datetime.now().strftime('%Y-%m-%d')}*")

    report_path = os.path.join(output_dir, f"爆款内容体检报告_{author_name}.md")
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(report))
    print(f"✅ 报告已生成: {report_path}")
    return top10


def download_audios(top10_df, audio_dir):
    """下载Top10音频"""
    os.makedirs(audio_dir, exist_ok=True)
    print(f"\n📥 开始下载 Top{len(top10_df)} 音频到 {audio_dir}")
    for idx, (_, row) in enumerate(top10_df.iterrows(), 1):
        url = str(row.get('音频文件链接', ''))
        if not url or url in ('0', '0.0', 'nan', ''):
            print(f"  [{idx:02d}] 无音频链接，跳过")
            continue
        title = clean_title(row['视频描述'])
        filename = f"{idx:02d}_{title}.mp3"
        filepath = os.path.join(audio_dir, filename)
        if os.path.exists(filepath) and os.path.getsize(filepath) > 1000:
            print(f"  [{idx:02d}] {filename} 已存在，跳过")
            continue
        try:
            r = requests.get(url, timeout=30)
            if r.status_code == 200 and len(r.content) > 1000:
                with open(filepath, 'wb') as f:
                    f.write(r.content)
                print(f"  [{idx:02d}] ✓ 下载成功: {filename} ({len(r.content)//1024}KB)")
            else:
                print(f"  [{idx:02d}] ✗ 下载失败: {filename} (status={r.status_code})")
        except Exception as e:
            print(f"  [{idx:02d}] ✗ 异常: {filename} ({e})")


def basic_fix_corpus(content):
    """OpenCC繁简转换 + 基础错别字规则修复"""
    converter = opencc.OpenCC('tw2s')
    text = converter.convert(content)

    fixes = [
        ('品位', '品类'),
        ('负构好', '复购好'),
        ('来钱卖', '来钱慢'),
        ('这把对话', '这八句话'),
        ('黨共', '打工'),
        ('總統人', '普通人'),
        ('細織', '信任'),
        ('創意想要沉默', '创业想要成功'),
        ('一言是干', '事业是干'),
        ('我治疗', '利润'),
        ('条件书', '书本上'),
        ('备观', '悲观'),
        ('執习', '执行'),
        ('难易執行', '难以置信'),
        ('轻自产', '轻资产'),
        ('半读', '半身的'),
        ('堂', '长'),
        ('próp钱', '花钱'),
        ('vitamin', '付费'),
        ('三一乐', '订阅'),
        ('火营', '火了一样'),
        ('看 pues', '看吧'),
        ('窮', '穷'),
        ('賺', '赚'),
        ('錢', '钱'),
        ('創業', '创业'),
        ('認知', '认知'),
        ('學習', '学习'),
        ('複製', '复制'),
        ('項目', '项目'),
        ('思維', '思维'),
        ('時候', '时候'),
        ('選擇', '选择'),
        ('開始', '开始'),
        ('別人', '别人'),
        ('這個', '这个'),
        ('這樣', '这样'),
        ('說過', '说过'),
        ('將', '将'),
        ('對', '对'),
        ('幫助', '帮助'),
        ('執行', '执行'),
        ('競爭', '竞争'),
        ('厲害', '厉害'),
        ('老闆', '老板'),
        ('並', '并'),
        ('騙人', '骗人'),
        ('共贏', '共赢'),
        ('來', '来'),
        ('賣', '卖'),
        ('輩子', '辈子'),
        ('窮人', '穷人'),
        ('麼', '么'),
        ('攢夠', '攒够'),
        ('機會', '机会'),
        ('動靜', '东西'),
        ('顧及', '顾及'),
        ('特別', '特别'),
        ('點', '点'),
        ('風水', '风水'),
        ('順利', '顺利'),
        ('和諧', '和谐'),
        ('財運', '财运'),
        ('說', '说'),
        ('才會', '才会'),
        ('遠', '远'),
        ('處', '处'),
        ('務', '务'),
    ]
    for old, new in fixes:
        text = text.replace(old, new)

    # 修正 OpenCC 误替换
    text = text.replace('什幺', '什么')
    text = text.replace('那幺', '那么')
    text = text.replace('怎幺', '怎么')

    return text


def transcribe_audios(audio_dir, corpus_dir, model_path):
    """转写音频为纯净版语料"""
    os.makedirs(corpus_dir, exist_ok=True)
    files = sorted([f for f in os.listdir(audio_dir) if f.endswith('.mp3')])
    if not files:
        print("\n⚠️ 音频目录为空，跳过转写")
        return

    print(f"\n🎙️ 开始转写 {len(files)} 条音频（模型: {os.path.basename(model_path)}）")
    for idx, fname in enumerate(files, 1):
        fpath = os.path.join(audio_dir, fname)
        if os.path.getsize(fpath) < 1000:
            print(f"  [{idx}] 跳过空文件: {fname}")
            continue

        base = fname[:-4]
        out_path = os.path.join(corpus_dir, f"{base}.md")
        if os.path.exists(out_path) and os.path.getsize(out_path) > 50:
            print(f"  [{idx}] {base}.md 已存在，跳过")
            continue

        print(f"  [{idx}] 转写: {fname}")
        try:
            result = subprocess.run(
                [WHISPER_CLI, "-m", model_path, "-f", fpath, "-l", "zh", "--output-txt", "-"],
                capture_output=True, text=True, timeout=600
            )
            raw = result.stdout
            raw = re.sub(r'\[\d{2}:\d{2}:\d{2}\.\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}\.\d{3}\]\s*', '', raw)
            raw = re.sub(r'\(\d{2}:\d{2}:\d{2}\.\d{3}\)', '', raw)
            cleaned = basic_fix_corpus(raw.strip())

            with open(out_path, 'w', encoding='utf-8') as f:
                f.write(f"标题：{base}\n")
                f.write("文案：\n")
                f.write("---\n")
                f.write(cleaned)
            print(f"       ✓ 完成")
        except Exception as e:
            print(f"       ✗ 失败: {e}")


def main():
    parser = argparse.ArgumentParser(description="对标账号全自动拆解")
    parser.add_argument("excel", help="Excel文件路径")
    default_out = get_default_output_dir()
    parser.add_argument("--out", "-o", default=default_out, help=f"输出目录（默认: {default_out}）")
    args = parser.parse_args()

    excel_path = args.excel
    if not os.path.exists(excel_path):
        print(f"❌ 文件不存在: {excel_path}")
        sys.exit(1)

    output_base = args.out
    os.makedirs(output_base, exist_ok=True)

    print(f"📂 读取数据: {excel_path}")
    df = pd.read_excel(excel_path, sheet_name=0)
    df = df.dropna(subset=['视频描述'])
    df = df.fillna(0)

    for col in ['点赞量', '收藏量', '评论量', '分享量']:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)

    df['interaction_score'] = (
        df['点赞量'] * 1.0 + df['收藏量'] * 1.5 +
        df['评论量'] * 2.0 + df['分享量'] * 2.5
    )

    # 解析时长与时段
    df['时长秒'] = df['视频时长'].apply(parse_duration)
    df['时长区间'] = df['时长秒'].apply(duration_bucket)
    df['发布时段'] = pd.to_datetime(df['发布时间'], errors='coerce').apply(time_bucket)
    df['主题'] = df.apply(classify_topic, axis=1)

    author = get_author_name(df)
    print(f"👤 博主: {author}")

    output_dir = os.path.join(output_base, author)
    os.makedirs(output_dir, exist_ok=True)
    print(f"📁 输出目录: {output_dir}")

    # 备份原始Excel
    raw_dir = os.path.join(output_dir, "原始数据")
    os.makedirs(raw_dir, exist_ok=True)
    basename = os.path.basename(excel_path)
    backup_path = os.path.join(raw_dir, basename)
    if not os.path.exists(backup_path):
        import shutil
        shutil.copy2(excel_path, backup_path)

    # 生成报告
    print("\n📊 生成爆款内容体检报告...")
    top10 = generate_report(df, author, output_dir)

    # 下载音频
    audio_dir = os.path.join(output_dir, "音频")
    download_audios(top10, audio_dir)

    # 转写语料
    corpus_dir = os.path.join(output_dir, "语料")
    model = ensure_model()
    transcribe_audios(audio_dir, corpus_dir, model)

    print(f"\n✅ 全部完成！案例已保存到: {output_dir}")


if __name__ == "__main__":
    main()
