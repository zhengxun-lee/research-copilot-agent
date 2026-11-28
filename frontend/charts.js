// Official modular ECharts imports: only line charts, grid, tooltip and SVG renderer.
import { init, use } from "echarts/core";
import { LineChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import { SVGRenderer } from "echarts/renderers";
use([LineChart, GridComponent, TooltipComponent, SVGRenderer]);
export { init };
