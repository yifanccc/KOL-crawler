import { CircleHelp } from "lucide-react";


const metricDefinitions = [
  {
    term: "账户保证金余额",
    description: "Binance Copy 组合详情的 marginBalance 原值；系统不把它拆成可用保证金和占用保证金。",
  },
  {
    term: "已估算持仓总额",
    description: "方向与数量已确认仓位的绝对名义金额之和，即持仓数量 × 标记价格，多空均按正数计入；待确认仓位不计入。",
  },
  {
    term: "仓位倍数（估算）",
    description: "已估算持仓总额 ÷ 账户保证金余额，用于衡量已知总体敞口；它不是交易所设置的合约杠杆。",
  },
  {
    term: "多头 / 空头仓位",
    description: "分别汇总方向和金额已知的多头、空头仓位；占账户倍数为单侧名义金额 ÷ 账户保证金余额，占比只在已计入的多空仓位之间计算。",
  },
  {
    term: "推算开仓价 / 持仓数量",
    description: "按连续成交记录重建。数量按成交净额累计，加仓后的开仓价按成交数量加权；单位跟随对应合约。",
  },
  {
    term: "标记价格",
    description: "Binance Futures 标记价格，不是最新成交价，用于计算名义金额与预计盈亏。",
  },
  {
    term: "预计盈亏",
    description: "多仓为（标记价 − 推算开仓价）× 数量，空仓反向计算；KOL 数值为可估算仓位之和，待确认仓位不计入，且不含手续费与资金费。",
  },
  {
    term: "成交均价 / 数量 / 金额",
    description: "均价和数量来自该条已成交记录；成交金额由成交均价 × 成交数量计算。",
  },
  {
    term: "已实现盈亏",
    description: "该条成交记录随单返回的 totalPnl 原值，仅在非零时展示。",
  },
  {
    term: "数据状态",
    description: "“指标齐全”仅表示账户余额、全部当前仓位名义金额和预计盈亏都有值且无陈旧/未知仓位，不代表成交历史完整。",
  },
];


export function PositionMetricGuide() {
  return (
    <details className="position-metric-guide">
      <summary>
        <CircleHelp size={16} aria-hidden="true" />
        指标口径与数据边界
      </summary>
      <dl>
        {metricDefinitions.map((item) => (
          <div key={item.term}>
            <dt>{item.term}</dt>
            <dd>{item.description}</dd>
          </div>
        ))}
      </dl>
      <p>
        当前 Binance Copy 成交记录不提供真实合约杠杆、占用保证金和强平价，页面与 NTFY 推送均不展示，也不使用默认值补齐。
      </p>
    </details>
  );
}
