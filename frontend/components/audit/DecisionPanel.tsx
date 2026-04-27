'use client';

import { motion } from 'framer-motion';
import { AlertTriangle, Lightbulb, Target, TrendingUp, Info } from 'lucide-react';
import { DecisionSummary } from '@/lib/api';

interface DecisionPanelProps {
  summary?: DecisionSummary;
}

export function DecisionPanel({ summary }: DecisionPanelProps) {
  if (!summary) return null;

  return (
    <motion.div 
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="glass-card overflow-hidden border-maroon/30 shadow-maroon-glow"
    >
      <div className="bg-maroon/10 px-6 py-4 border-b border-maroon/20 flex items-center justify-between">
        <h3 className="font-bold text-lg text-text-primary flex items-center gap-2">
          <Target size={20} className="text-red" />
          Decision Summary
        </h3>
        <div className="flex items-center gap-2 text-xs font-medium text-maroon-light bg-maroon/5 px-3 py-1 rounded-full border border-maroon/10">
          <Info size={12} />
          Executive Guidance
        </div>
      </div>
      
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 divide-y md:divide-y-0 md:divide-x divide-white/5">
        {/* Problem */}
        <div className="p-6 space-y-3">
          <div className="flex items-center gap-2 text-red font-bold text-xs uppercase tracking-widest">
            <AlertTriangle size={14} /> Problem
          </div>
          <p className="text-sm font-medium text-text-primary leading-relaxed">
            {summary.problem}
          </p>
        </div>

        {/* Cause */}
        <div className="p-6 space-y-3">
          <div className="flex items-center gap-2 text-amber-500 font-bold text-xs uppercase tracking-widest">
            <TrendingUp size={14} /> Root Cause
          </div>
          <p className="text-sm text-text-secondary leading-relaxed">
            {summary.cause}
          </p>
        </div>

        {/* Recommendation */}
        <div className="p-6 space-y-3">
          <div className="flex items-center gap-2 text-emerald-500 font-bold text-xs uppercase tracking-widest">
            <Lightbulb size={14} /> Action
          </div>
          <p className="text-sm text-text-secondary leading-relaxed">
            {summary.recommendation}
          </p>
        </div>

        {/* Impact */}
        <div className="p-6 space-y-3 bg-white/[0.02]">
          <div className="flex items-center gap-2 text-maroon-light font-bold text-xs uppercase tracking-widest">
            <TrendingUp size={14} /> Impact
          </div>
          <p className="text-sm font-semibold text-text-primary leading-relaxed">
            {summary.expected_impact}
          </p>
        </div>
      </div>
    </motion.div>
  );
}
