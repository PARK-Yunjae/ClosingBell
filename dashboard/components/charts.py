"""
차트 컴포넌트

Plotly 기반 차트 렌더링 함수들
"""

import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
from typing import List, Dict, Optional, Any
from datetime import date


def render_score_radar_chart(score_detail: Dict[str, float], title: str = "점수 분포") -> go.Figure:
    """5가지 지표 점수 레이더 차트
    
    Args:
        score_detail: 점수 딕셔너리
        title: 차트 제목
        
    Returns:
        Plotly Figure
    """
    categories = ['CCI 값', 'CCI 기울기', 'MA20 기울기', '양봉 품질', '상승률']
    values = [
        score_detail.get('score_cci_value', 0),
        score_detail.get('score_cci_slope', 0),
        score_detail.get('score_ma20_slope', 0),
        score_detail.get('score_candle', 0),
        score_detail.get('score_change', 0),
    ]
    
    # 레이더 차트를 위해 마지막 값을 첫 값으로 복사
    values_closed = values + [values[0]]
    categories_closed = categories + [categories[0]]
    
    fig = go.Figure()
    
    fig.add_trace(go.Scatterpolar(
        r=values_closed,
        theta=categories_closed,
        fill='toself',
        fillcolor='rgba(102, 126, 234, 0.3)',
        line=dict(color='rgba(102, 126, 234, 1)', width=2),
        name='점수',
    ))
    
    fig.update_layout(
        polar=dict(
            radialaxis=dict(
                visible=True,
                range=[0, 10],
                tickfont=dict(size=10),
            ),
            angularaxis=dict(
                tickfont=dict(size=12),
            ),
        ),
        showlegend=False,
        title=dict(text=title, x=0.5),
        height=350,
        margin=dict(l=60, r=60, t=60, b=60),
    )
    
    return fig


def render_candlestick_chart(
    daily_prices: List[Dict],
    title: str = "일봉 차트",
    show_ma20: bool = True,
    show_volume: bool = True,
) -> go.Figure:
    """캔들스틱 차트
    
    Args:
        daily_prices: 일봉 데이터 리스트
        title: 차트 제목
        show_ma20: MA20 표시 여부
        show_volume: 거래량 표시 여부
        
    Returns:
        Plotly Figure
    """
    if not daily_prices:
        fig = go.Figure()
        fig.add_annotation(text="데이터가 없습니다", xref="paper", yref="paper", x=0.5, y=0.5)
        return fig
    
    # 데이터 준비
    dates = [p.get('date', '') for p in daily_prices]
    opens = [p.get('open', 0) for p in daily_prices]
    highs = [p.get('high', 0) for p in daily_prices]
    lows = [p.get('low', 0) for p in daily_prices]
    closes = [p.get('close', 0) for p in daily_prices]
    volumes = [p.get('volume', 0) for p in daily_prices]
    
    # 서브플롯 생성
    if show_volume:
        fig = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.05,
            row_heights=[0.7, 0.3],
        )
    else:
        fig = go.Figure()
    
    # 캔들스틱
    candlestick = go.Candlestick(
        x=dates,
        open=opens,
        high=highs,
        low=lows,
        close=closes,
        increasing_line_color='#ef5350',  # 상승: 빨강
        decreasing_line_color='#26a69a',  # 하락: 파랑
        name='가격',
    )
    
    if show_volume:
        fig.add_trace(candlestick, row=1, col=1)
    else:
        fig.add_trace(candlestick)
    
    # MA20
    if show_ma20 and len(closes) >= 20:
        ma20_values = []
        for i in range(len(closes)):
            if i >= 19:
                ma20 = sum(closes[i-19:i+1]) / 20
                ma20_values.append(ma20)
            else:
                ma20_values.append(None)
        
        ma20_trace = go.Scatter(
            x=dates,
            y=ma20_values,
            mode='lines',
            line=dict(color='orange', width=1.5),
            name='MA20',
        )
        
        if show_volume:
            fig.add_trace(ma20_trace, row=1, col=1)
        else:
            fig.add_trace(ma20_trace)
    
    # 거래량
    if show_volume:
        colors = ['#ef5350' if c >= o else '#26a69a' for c, o in zip(closes, opens)]
        
        volume_trace = go.Bar(
            x=dates,
            y=volumes,
            marker_color=colors,
            name='거래량',
        )
        fig.add_trace(volume_trace, row=2, col=1)
        
        fig.update_yaxes(title_text="가격", row=1, col=1)
        fig.update_yaxes(title_text="거래량", row=2, col=1)
    
    # 레이아웃
    fig.update_layout(
        title=dict(text=title, x=0.5),
        xaxis_rangeslider_visible=False,
        height=500 if show_volume else 400,
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    
    return fig


def render_correlation_heatmap(correlations: Dict[str, float], title: str = "지표 상관관계") -> go.Figure:
    """상관관계 히트맵
    
    Args:
        correlations: 지표별 상관계수
        title: 차트 제목
        
    Returns:
        Plotly Figure
    """
    if not correlations:
        fig = go.Figure()
        fig.add_annotation(text="데이터가 없습니다", xref="paper", yref="paper", x=0.5, y=0.5)
        return fig
    
    indicators = list(correlations.keys())
    values = list(correlations.values())
    
    # 바 차트
    colors = ['#26a69a' if v >= 0 else '#ef5350' for v in values]
    
    fig = go.Figure(go.Bar(
        x=indicators,
        y=values,
        marker_color=colors,
        text=[f"{v:+.3f}" for v in values],
        textposition='outside',
    ))
    
    fig.update_layout(
        title=dict(text=title, x=0.5),
        xaxis_title="지표",
        yaxis_title="상관계수",
        yaxis_range=[-1, 1],
        height=350,
    )
    
    # 0 기준선
    fig.add_hline(y=0, line_dash="dash", line_color="gray")
    
    return fig


def render_performance_line_chart(
    performance_data: List[Dict],
    title: str = "성과 추이",
) -> go.Figure:
    """누적 성과 라인 차트
    
    Args:
        performance_data: 일별 성과 데이터
        title: 차트 제목
        
    Returns:
        Plotly Figure
    """
    if not performance_data:
        fig = go.Figure()
        fig.add_annotation(text="데이터가 없습니다", xref="paper", yref="paper", x=0.5, y=0.5)
        return fig
    
    dates = [d.get('date', '') for d in performance_data]
    gap_rates = [d.get('gap_rate', 0) for d in performance_data]
    
    # 누적 수익률 계산
    cumulative = []
    total = 0
    for rate in gap_rates:
        total += rate
        cumulative.append(total)
    
    fig = go.Figure()
    
    # 누적 수익률
    fig.add_trace(go.Scatter(
        x=dates,
        y=cumulative,
        mode='lines+markers',
        line=dict(color='#667eea', width=2),
        marker=dict(size=6),
        fill='tozeroy',
        fillcolor='rgba(102, 126, 234, 0.2)',
        name='누적 수익률',
    ))
    
    fig.update_layout(
        title=dict(text=title, x=0.5),
        xaxis_title="날짜",
        yaxis_title="누적 수익률 (%)",
        height=350,
    )
    
    # 0 기준선
    fig.add_hline(y=0, line_dash="dash", line_color="gray")
    
    return fig


def render_weight_history_chart(
    weight_history: List[Dict],
    title: str = "가중치 변화 추이",
) -> go.Figure:
    """가중치 변화 추이 차트
    
    Args:
        weight_history: 가중치 변경 이력
        title: 차트 제목
        
    Returns:
        Plotly Figure
    """
    if not weight_history:
        fig = go.Figure()
        fig.add_annotation(text="데이터가 없습니다", xref="paper", yref="paper", x=0.5, y=0.5)
        return fig
    
    # 지표별로 그룹화
    indicators = set(h.get('indicator', '') for h in weight_history)
    
    fig = go.Figure()
    
    colors = px.colors.qualitative.Set2
    for i, indicator in enumerate(sorted(indicators)):
        history = [h for h in weight_history if h.get('indicator') == indicator]
        dates = [h.get('changed_at', '') for h in history]
        weights = [h.get('new_weight', 1.0) for h in history]
        
        fig.add_trace(go.Scatter(
            x=dates,
            y=weights,
            mode='lines+markers',
            name=indicator,
            line=dict(color=colors[i % len(colors)]),
        ))
    
    fig.update_layout(
        title=dict(text=title, x=0.5),
        xaxis_title="날짜",
        yaxis_title="가중치",
        yaxis_range=[0, 5.5],
        height=350,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    
    return fig


def render_win_rate_gauge(win_rate: float, title: str = "승률") -> go.Figure:
    """승률 게이지 차트
    
    Args:
        win_rate: 승률 (%)
        title: 차트 제목
        
    Returns:
        Plotly Figure
    """
    # 색상 결정
    if win_rate >= 60:
        color = "#26a69a"  # 녹색
    elif win_rate >= 40:
        color = "#ffa726"  # 노란색
    else:
        color = "#ef5350"  # 빨간색
    
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=win_rate,
        title={'text': title, 'font': {'size': 16}},
        number={'suffix': '%', 'font': {'size': 24}},
        gauge={
            'axis': {'range': [0, 100], 'tickwidth': 1},
            'bar': {'color': color},
            'bgcolor': 'white',
            'steps': [
                {'range': [0, 40], 'color': 'rgba(239, 83, 80, 0.3)'},
                {'range': [40, 60], 'color': 'rgba(255, 167, 38, 0.3)'},
                {'range': [60, 100], 'color': 'rgba(38, 166, 154, 0.3)'},
            ],
            'threshold': {
                'line': {'color': 'black', 'width': 2},
                'thickness': 0.75,
                'value': 50,
            },
        },
    ))
    
    fig.update_layout(
        height=200,
        margin=dict(l=20, r=20, t=40, b=20),
    )
    
    return fig
