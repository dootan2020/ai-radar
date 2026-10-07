import React from 'react';
import { Composition } from 'remotion';
import { MainVideo } from './MainVideo.jsx';

// Default mock props for Remotion Studio preview
const defaultStories = [
  {
    id: 'a08a24d3f61d4df508c8',
    title: 'The 7-year-old Nvidia Shield TV is now $100 more expensive due to AI',
    title_vi: 'Nvidia Shield TV 7 năm tuổi bây giờ là $ 100 đắt hơn do AI',
    summary_vi: 'Ban đầu ra mắt vào năm 2019, Nvidia Shield TV Pro bây giờ bán lẻ với giá 299,99 đô la.',
    scriptLine: 'Nvidia Shield TV Pro, ra mắt từ 2019, giờ bán 299,99 đô la, đắt hơn 100 đô la vì AI.',
    worth_score: 6.99,
    coverage: [
      { publisher: 'Ars Technica', source: 'ars-technica-ai' },
      { publisher: 'The Verge', source: 'the-verge-ai' },
    ],
    imageUrl: 'https://cdn.arstechnica.net/wp-content/uploads/2026/01/Shield-10-yrs-1-1152x648.jpg',
  },
  {
    id: '5432f5b94c34f514ec03',
    title: 'Apple says it’s tightening macOS ‘Full Disk Access’ controls due to new risks from AI agents',
    title_vi: 'Apple thắt chặt quyền Full Disk Access trên macOS do rủi ro từ các AI agent',
    summary_vi: 'Apple cảnh báo rằng các agent AI có khả năng ngày càng cao sẽ khiến việc truy cập rộng vào tệp và tin nhắn trở nên nguy hiểm hơn.',
    scriptLine: 'Apple siết quyền truy cập toàn bộ ổ đĩa trên macOS. Lý do: các AI agent ngày càng có thể đọc tệp, tin nhắn, thư và lịch sử duyệt web của bạn.',
    worth_score: 6.33,
    coverage: [
      { publisher: 'TechCrunch', source: 'techcrunch-ai' },
      { publisher: '9to5Mac', source: '9to5mac' },
    ],
    imageUrl: 'https://techcrunch.com/wp-content/uploads/2022/07/CMC_1580.jpg?resize=1200,800',
  },
  {
    id: '90c6c9903271281ae042',
    title: 'Amazon’s $1B plan to combat data center backlash draws more backlash',
    title_vi: 'Kế hoạch 1 tỷ USD của Amazon để chống lại phản ứng trung tâm dữ liệu thu hút nhiều phản ứng hơn',
    summary_vi: 'Amazon khen ngợi việc chấm dứt NDA nhưng chỉ trích vì làm giảm thiểu ô nhiễm trung tâm dữ liệu.',
    scriptLine: 'Amazon chi 1 tỷ đô la để xoa dịu phản ứng về trung tâm dữ liệu, nhưng lại bị chỉ trích là đang làm nhẹ đi chuyện ô nhiễm.',
    worth_score: 7.14,
    coverage: [
      { publisher: 'Ars Technica', source: 'ars-technica-ai' },
      { publisher: 'The Verge', source: 'the-verge-ai' },
    ],
    imageUrl: 'https://cdn.arstechnica.net/wp-content/uploads/2026/10/GettyImages-2292181016.jpg',
  },
];

export const RemotionRoot = () => {
  return (
    <>
      <Composition
        id="AiRadarDailyVideo"
        component={MainVideo}
        durationInFrames={1085}
        calculateMetadata={({props}) => ({
          durationInFrames: props.totalDurationFrames || 1085,
        })}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{
          stories: defaultStories,
          snapshotDate: 'Thứ Ba, 6 tháng 10, 2026',
          totalStoriesCount: 323,
          windowHours: 72,
          introFrames: 260,
          outroFrames: 193,
          storyDurations: [201, 232, 199],
          totalDurationFrames: 1085,
          script: {
            hook: 'AI vừa khiến một chiếc TV box 7 năm tuổi đắt thêm 100 đô la. Và đó chưa phải tin lạ nhất hôm nay.',
            hint: 'Ba tin AI đáng chú ý nhất, trong 45 giây.',
            cta: 'Mỗi sáng ai-radar chọn 3 tin AI đáng đọc nhất. Theo dõi kênh để cập nhật tin AI nóng nhất. Bạn quan tâm tin nào nhất? Bình luận cho mình biết nhé.',
          },
        }}
      />
    </>
  );
};
