<script setup lang="ts">
// 隐私政策（网站与 iOS App 共用，App Store 的隐私政策链接指向这里）：静态文字，按页面语言显示
import { type Locale, localePath, translate } from "../i18n";
import LogoMark from "./LogoMark.vue";
import "@mapette/core/mapette.css";
import "../theme.css";

const props = defineProps<{ lang: Locale }>();

const UPDATED = "2026-10-25";
const ISSUES = "https://github.com/Jannchie/junrei/issues";

/** 每种语言：标题、导语、各条（标题 + 正文）、反馈 */
const TEXT: Record<Locale, { title: string; intro: string; items: [string, string][]; contact: string; updated: string }> = {
  "zh-Hans": {
    title: "隐私政策",
    intro: "本政策适用于圣地巡礼地图网站（junrei.jannchie.com）与 iOS App。我们不收集、不存储、也不分享任何个人数据：没有账号、统计、广告或追踪。",
    items: [
      ["位置", "只有在你点定位按钮并允许访问后，才会在你的设备上用位置在地图上显示你在哪里，不会发送到任何地方。"],
      ["设备上保存的设置", "网站在浏览器本地保存外观偏好与「显示成人向作品」的选择，并缓存页面以便离线打开；这些只存在你的设备上。"],
      ["网络请求", "为显示地图和地点，会从 junrei.jannchie.com、cdn.jannchie.com 获取数据，从 tiles.openfreemap.org 获取底图，从 AWS 获取地形，从 image.anitabi.cn 等各地点标明的来源获取图片。与任何网页请求一样，这些服务器会在连接中获知你的 IP 地址和设备类型；我们不发送其他信息，也不会用这些日志识别你。"],
      ["外部链接", "来源、Bangumi、Anitabi、地图或 GitHub 等链接会打开其他网站或 App，适用它们各自的隐私政策。"],
    ],
    contact: "问题反馈",
    updated: "更新于",
  },
  "zh-Hant": {
    title: "隱私政策",
    intro: "本政策適用於聖地巡禮地圖網站（junrei.jannchie.com）與 iOS App。我們不收集、不儲存、也不分享任何個人資料：沒有帳號、統計、廣告或追蹤。",
    items: [
      ["位置", "只有在你點定位按鈕並允許存取後，才會在你的裝置上用位置在地圖上顯示你在哪裡，不會傳送到任何地方。"],
      ["裝置上儲存的設定", "網站在瀏覽器本機儲存外觀偏好與「顯示成人向作品」的選擇，並快取頁面以便離線開啟；這些只存在你的裝置上。"],
      ["網路請求", "為顯示地圖和地點，會從 junrei.jannchie.com、cdn.jannchie.com 取得資料，從 tiles.openfreemap.org 取得底圖，從 AWS 取得地形，從 image.anitabi.cn 等各地點標明的來源取得圖片。與任何網頁請求一樣，這些伺服器會在連線中得知你的 IP 位址和裝置類型；我們不傳送其他資訊，也不會用這些記錄識別你。"],
      ["外部連結", "來源、Bangumi、Anitabi、地圖或 GitHub 等連結會開啟其他網站或 App，適用它們各自的隱私政策。"],
    ],
    contact: "問題回報",
    updated: "更新於",
  },
  ja: {
    title: "プライバシーポリシー",
    intro: "本ポリシーは聖地巡礼マップのウェブサイト（junrei.jannchie.com）と iOS アプリに適用されます。個人データの収集・保存・共有は行いません。アカウント、解析、広告、トラッキングはありません。",
    items: [
      ["位置情報", "現在地ボタンを押して許可した場合のみ、端末上で地図に現在地を表示するために使います。どこにも送信しません。"],
      ["端末に保存する設定", "ウェブサイトは外観の設定と「成人向け作品を表示」の選択をブラウザ内に保存し、オフラインで開けるようページをキャッシュします。いずれも端末内にのみ保存されます。"],
      ["通信", "地図とスポットを表示するため、junrei.jannchie.com・cdn.jannchie.com からデータを、tiles.openfreemap.org から地図タイルを、AWS から地形データを、image.anitabi.cn など各スポットの出典から画像を取得します。通常の Web 通信と同様に、これらのサーバーは接続に伴って IP アドレスと端末の種類を受け取ります。それ以外の情報は送信せず、これらの記録で利用者を特定することもありません。"],
      ["外部リンク", "出典、Bangumi、Anitabi、マップ、GitHub などへのリンクは他のサイトやアプリで開き、それぞれのプライバシーポリシーが適用されます。"],
    ],
    contact: "お問い合わせ",
    updated: "更新日",
  },
  en: {
    title: "Privacy Policy",
    intro: "This policy covers the Anime Pilgrimage Map website (junrei.jannchie.com) and iOS app. We do not collect, store or share personal data. There are no accounts, analytics, advertising or tracking.",
    items: [
      ["Location", "Only if you tap the locate button and allow access, your location is used on your device to show where you are on the map. It is never sent anywhere."],
      ["Settings on your device", "The website keeps your appearance setting and the \"show adult titles\" choice in your browser, and caches pages so they open offline. These stay on your device."],
      ["Network requests", "To show the map and spots, data is loaded from junrei.jannchie.com and cdn.jannchie.com, map tiles from tiles.openfreemap.org, terrain from AWS, and images from image.anitabi.cn and other sources named by each spot. Like any web request, these servers receive your IP address and device type as part of the connection; nothing else is sent, and we do not use these logs to identify you."],
      ["External links", "Links to sources, Bangumi, Anitabi, Maps or GitHub open other websites or apps, which have their own privacy policies."],
    ],
    contact: "Questions",
    updated: "Last updated",
  },
};
const text = TEXT[props.lang];
</script>

<template>
  <main class="privacy">
    <a class="brand" :href="localePath(lang, '/')"><LogoMark :size="22" /><span>{{ translate(lang, "brand") }}</span></a>
    <h1>{{ text.title }}</h1>
    <p class="muted">{{ text.updated }} {{ UPDATED }}</p>
    <p>{{ text.intro }}</p>
    <section v-for="[title, body] in text.items" :key="title">
      <h2>{{ title }}</h2>
      <p>{{ body }}</p>
    </section>
    <p>{{ text.contact }}：<a :href="ISSUES">{{ ISSUES }}</a></p>
  </main>
</template>

<style scoped>
.privacy {
  max-width: 680px;
  margin: 0 auto;
  padding: 32px 16px 64px;
  line-height: 1.7;
  font-family: -apple-system, system-ui, sans-serif;
}
.brand {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  text-decoration: none;
}
h1 {
  margin: 24px 0 4px;
  font-size: 28px;
}
h2 {
  margin: 24px 0 4px;
  font-size: 17px;
}
p {
  margin: 8px 0;
}
.muted {
  color: var(--muted);
  font-size: 14px;
}
a {
  color: var(--accent);
}
</style>

<style>
html,
body {
  margin: 0;
  background: var(--bg-solid);
  color: var(--fg);
}
</style>
