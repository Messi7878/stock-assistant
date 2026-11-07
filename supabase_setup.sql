-- ============================================================
-- A股助手 · Supabase 建表脚本
-- 用法:Supabase 控制台 -> 左侧 SQL Editor -> New query -> 粘贴全部 -> Run
-- ============================================================

create table if not exists public.kv (
  "user"     text        not null,   -- 登录用户名
  "key"      text        not null,   -- portfolio / watchlist / total_capital
  "value"    jsonb,                  -- 任意 JSON
  updated_at timestamptz not null default now(),
  primary key ("user", "key")
);

-- 关掉行级安全:只有拿着项目 anon key 的服务端才能访问,
-- 而 anon key 只写在 Streamlit 的 Secrets 里,不会暴露给浏览器。
alter table public.kv disable row level security;

grant select, insert, update, delete on public.kv to anon, authenticated;

-- 验证:应返回空表结构,不报错
select * from public.kv limit 1;
