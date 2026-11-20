const manualChapters = [
  {
    "name": "導入・利用開始",
    "description": "初期台帳の準備、職員・保護者の登録からログインまで。",
    "topics": [
      {
        "title": "利用開始から初期設定の流れ",
        "url": "#chapter/0",
        "role": "管理者・導入担当",
        "kind": "概要",
        "source": "MANUAL.md 第1章"
      },
      {
        "title": "職員登録・QR案内・パスワード再設定",
        "url": "#article/staff",
        "role": "管理者・職員本人",
        "kind": "操作手順",
        "source": "MANUAL.md 第2章"
      },
      {
        "title": "パスワードを忘れてログインできないとき",
        "url": "#article/password",
        "role": "職員本人・管理者",
        "kind": "操作手順",
        "source": "MANUAL.md 第2章"
      },
      {
        "title": "共通QRで保護者の初回登録・新入園児受付",
        "url": "#article/parent-qr",
        "role": "管理者・保護者本人",
        "kind": "操作手順",
        "source": "MANUAL.md 第2章"
      },
      {
        "title": "兄弟姉妹の追加・家族アカウントの紐付け",
        "url": "#article/child-sibling",
        "role": "管理者・保護者本人",
        "kind": "操作手順",
        "source": "MANUAL.md 第2章"
      },
      {
        "title": "在園児の保護者を個別に招待する",
        "url": "#article/parent",
        "role": "管理者",
        "kind": "操作手順",
        "source": "MANUAL.md 第2章"
      },
      {
        "title": "Windows園内LAN・外部アクセス設定",
        "url": "#chapter/0",
        "role": "システム担当",
        "kind": "環境構築",
        "source": "MANUAL.md 第1章"
      }
    ]
  },
  {
    "name": "日々の業務・登降園",
    "description": "朝の出欠、玄関キオスク打刻、連絡帳、お迎え予定。",
    "topics": [
      {
        "title": "玄関キオスク：登園打刻（共通QRかざし）",
        "url": "#article/parent-arrival",
        "role": "保護者・現場職員",
        "kind": "操作手順",
        "source": "MANUAL.md 第3章"
      },
      {
        "title": "玄関キオスク：降園打刻とお迎え者確認",
        "url": "#article/parent-departure",
        "role": "保護者・現場職員",
        "kind": "操作手順",
        "source": "MANUAL.md 第3章"
      },
      {
        "title": "打刻漏れ・空欄時刻の一括補完",
        "url": "#article/clock",
        "role": "管理者・現場職員",
        "kind": "操作手順",
        "source": "MANUAL.md 第3章"
      },
      {
        "title": "電話での欠席・遅刻連絡の受付入力",
        "url": "#article/phone",
        "role": "現場職員",
        "kind": "操作手順",
        "source": "MANUAL.md 第3章"
      },
      {
        "title": "連絡帳のダブルチェック承認と公開フロー",
        "url": "#article/contact-approval",
        "role": "担任保育士・承認主任",
        "kind": "操作手順",
        "source": "MANUAL.md 第3章 4.6"
      },
      {
        "title": "お迎え予定の変更と閉園前チェック",
        "url": "#article/parent-app-pickup",
        "role": "保護者・現場職員",
        "kind": "操作手順",
        "source": "MANUAL.md 第3章 4.8"
      }
    ]
  },
  {
    "name": "園児・家庭・健康記録",
    "description": "園児台帳、緊急連絡先順位、医療同意、アレルギー管理。",
    "topics": [
      {
        "title": "園児台帳の直接登録・修正",
        "url": "#article/child",
        "role": "台帳担当",
        "kind": "操作手順",
        "source": "MANUAL.md 第2章"
      },
      {
        "title": "緊急連絡先の優先順位設定（第1〜第3連絡先）",
        "url": "#article/emergency-priority",
        "role": "台帳担当・保護者",
        "kind": "操作手順",
        "source": "MANUAL.md 第3章 4.2"
      },
      {
        "title": "救急搬送・レントゲン撮影の医療同意",
        "url": "#article/medical-consent",
        "role": "保護者・現場職員",
        "kind": "操作手順",
        "source": "MANUAL.md 第3章 4.5"
      },
      {
        "title": "健康管理一覧・園児サマリー・身体測定",
        "url": "health/",
        "role": "看護師・現場職員",
        "kind": "画面ガイド",
        "source": "health/index.html"
      },
      {
        "title": "アレルギー管理（品目・生活管理指導表）",
        "url": "health/allergies/",
        "role": "栄養士・看護師・担任",
        "kind": "画面ガイド",
        "source": "health/allergies/index.html"
      },
      {
        "title": "定期健康診断記録と成長曲線グラフ",
        "url": "health/checks/",
        "role": "看護師・現場職員",
        "kind": "画面ガイド",
        "source": "health/checks/index.html"
      }
    ]
  },
  {
    "name": "指導計画（年案・月案・週案・日案）",
    "description": "指導計画の作成、文例アシスト、レビュー依頼・承認。",
    "topics": [
      {
        "title": "指導計画ホーム・帳票一覧",
        "url": "plans/",
        "role": "担任・主任・施設長",
        "kind": "画面ガイド",
        "source": "plans/index.html"
      },
      {
        "title": "月案の作成・保存・レビュー依頼・印刷",
        "url": "plans/monthly/",
        "role": "クラス担任・承認者",
        "kind": "画面ガイド",
        "source": "plans/monthly/index.html"
      },
      {
        "title": "週案の作成・曜日別活動・下書き保存",
        "url": "plans/weekly/",
        "role": "クラス担任・承認者",
        "kind": "画面ガイド",
        "source": "plans/weekly/index.html"
      },
      {
        "title": "帳票検索（書きかけ・下書きの絞り込み）",
        "url": "plans/search/",
        "role": "担任・施設長",
        "kind": "画面ガイド",
        "source": "plans/search/index.html"
      }
    ]
  },
  {
    "name": "職員管理 & シフト自動作成 (NuShift)",
    "description": "希望休受付、配置基準ソルバー求解、ピン留め調整、確定公開。",
    "topics": [
      {
        "title": "NuShift シフト自動作成・ギャップ検知",
        "url": "#article/shift-auto",
        "role": "シフト作成担当・園長",
        "kind": "操作手順",
        "source": "MANUAL.md 第4章"
      },
      {
        "title": "シフトの手動調整とピン留め固定",
        "url": "#article/shift-pinning",
        "role": "シフト作成担当",
        "kind": "操作手順",
        "source": "MANUAL.md 第4章"
      },
      {
        "title": "職員権限・担当クラス・カレンダー共有",
        "url": "#chapter/4",
        "role": "施設長・管理者",
        "kind": "操作手順",
        "source": "MANUAL.md 第4章"
      }
    ]
  },
  {
    "name": "料金・請求 & 全銀口座振替",
    "description": "月次保育料・延長保育料の計算、兄弟割引、全銀振替、締め解除。",
    "topics": [
      {
        "title": "月次請求計算と全銀協（Zengin）振替データ出力",
        "url": "#article/billing-zengin",
        "role": "請求担当・園長",
        "kind": "操作手順",
        "source": "MANUAL.md 第5章"
      },
      {
        "title": "確定済み請求の締め解除（再オープン）",
        "url": "#article/billing-reopen",
        "role": "管理者・施設長",
        "kind": "操作手順",
        "source": "MANUAL.md 第5章 6.7"
      },
      {
        "title": "保育認定・延長料金マスタ設定",
        "url": "#chapter/5",
        "role": "施設長・事務担当",
        "kind": "マスタ設定",
        "source": "MANUAL.md 第5章"
      }
    ]
  },
  {
    "name": "保護者アプリ & 困りごと対応",
    "description": "保護者スマホポータル、プッシュ通知、バックアップと保守。",
    "topics": [
      {
        "title": "保護者アプリ：ホーム画面と主要機能",
        "url": "#article/parent-app-home",
        "role": "保護者",
        "kind": "画面ガイド",
        "source": "MANUAL.md 第3章"
      },
      {
        "title": "保護者アプリ：朝の体調連絡・検温",
        "url": "#article/parent-app-contact",
        "role": "保護者",
        "kind": "操作手順",
        "source": "MANUAL.md 第3章"
      },
      {
        "title": "保護者アプリ：お休み（欠席）連絡",
        "url": "#article/parent-app-absence",
        "role": "保護者",
        "kind": "操作手順",
        "source": "MANUAL.md 第3章"
      },
      {
        "title": "プッシュ通知設定（iPhone / Android）",
        "url": "#article/parent-app-notifications-iphone",
        "role": "保護者",
        "kind": "設定手順",
        "source": "MANUAL.md 第3章"
      },
      {
        "title": "バックアップの取得・復元と日常点検",
        "url": "#chapter/6",
        "role": "運用担当・管理者",
        "kind": "運用手順",
        "source": "MANUAL.md 第6章"
      }
    ]
  }
];
