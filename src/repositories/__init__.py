# -*- coding: utf-8 -*-
"""
===================================
数据访问层模块初始化
===================================

职责：
1. 导出所有 Repository 类
"""

from src.repositories.analysis_repo import AnalysisRepository
from src.repositories.ai_opinion_repo import AIOpinionRepository
from src.repositories.backtest_repo import BacktestRepository
from src.repositories.decision_signal_repo import DecisionSignalRepository
from src.repositories.decision_signal_outcome_repo import DecisionSignalOutcomeRepository
from src.repositories.investment_journal_repo import InvestmentJournalRepository
from src.repositories.stock_repo import StockRepository

__all__ = [
    "AnalysisRepository",
    "AIOpinionRepository",
    "BacktestRepository",
    "DecisionSignalRepository",
    "DecisionSignalOutcomeRepository",
    "InvestmentJournalRepository",
    "StockRepository",
]
