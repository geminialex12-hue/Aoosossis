import { useEffect, useState } from "react";

declare global {
  interface Window {
    Telegram?: {
      WebApp?: {
        initData: string;
        ready: () => void;
        expand: () => void;
        HapticFeedback?: {
          impactOccurred: (style: string) => void;
        };
      };
    };
  }
}

type Screen = "home" | "play" | "party" | "profile" | "stats" | "search" | "settings" | "premium" | "register";

type Profile = {
  nickname: string;
  game_id: string;
  elo: number;
  rank: string;
  wins: number;
  losses: number;
  kills: number;
  deaths: number;
  premium: boolean;
};

const API = import.meta.env.VITE_API_URL || `${location.protocol}//${location.hostname}:8000`;

function initData() {
  return window.Telegram?.WebApp?.initData || "";
}

async function api(path: string, options: RequestInit = {}) {
  const response = await fetch(`${API}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Telegram ${initData()}`,
      ...(options.headers || {})
    }
  });

  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || "Ошибка сервера");
  return data;
}

export default function App() {
  const [screen, setScreen] = useState<Screen>("home");
  const [profile, setProfile] = useState<Profile | null>(null);
  const [stats, setStats] = useState<any>(null);
  const [nickname, setNickname] = useState("");
  const [gameId, setGameId] = useState("");
  const [loading, setLoading] = useState(true);
  const [registered, setRegistered] = useState(false);
  const [queue, setQueue] = useState(false);
  const [queueTime, setQueueTime] = useState(0);
  const [search, setSearch] = useState("");
  const [players, setPlayers] = useState<any[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    window.Telegram?.WebApp?.ready();
    window.Telegram?.WebApp?.expand();
    boot();
  }, []);

  useEffect(() => {
    if (!queue) return;
    const id = setInterval(() => setQueueTime(v => v + 1), 1000);
    return () => clearInterval(id);
  }, [queue]);

  async function boot() {
    try {
      const auth = await api("/api/auth/telegram", {
        method: "POST",
        body: JSON.stringify({ init_data: initData() })
      });

      setRegistered(auth.registered);

      if (auth.registered) {
        await reload();
      } else {
        setScreen("register");
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function reload() {
    const [p, s] = await Promise.all([
      api("/api/profile"),
      api("/api/stats")
    ]);
    setProfile(p);
    setStats(s);
  }

  async function register() {
    try {
      setError("");
      await api("/api/auth/register", {
        method: "POST",
        body: JSON.stringify({
          nickname: nickname.trim(),
          game_id: gameId.trim()
        })
      });
      setRegistered(true);
      await reload();
      setScreen("home");
    } catch (e: any) {
      setError(e.message);
    }
  }

  async function joinQueue() {
    try {
      const result = await api("/api/matchmaking/join", {
        method: "POST",
        body: JSON.stringify({ region: "EU" })
      });

      if (result.status === "match_found") {
        alert(`Матч найден! ID: ${result.match_id}`);
      } else {
        setQueue(true);
        setQueueTime(0);
      }
    } catch (e: any) {
      setError(e.message);
    }
  }

  async function leaveQueue() {
    await api("/api/matchmaking/leave", { method: "POST" });
    setQueue(false);
    setQueueTime(0);
  }

  async function searchPlayers(value: string) {
    setSearch(value);
    if (value.length < 2) {
      setPlayers([]);
      return;
    }
    try {
      const data = await api(`/api/players/search?q=${encodeURIComponent(value)}`);
      setPlayers(data.players);
    } catch {}
  }

  if (loading) return <div className="loading"><b>STANDKNIFE</b><div className="spinner" /></div>;

  if (screen === "register" || !registered) {
    return (
      <div className="app center">
        <div className="logo">S</div>
        <span className="eyebrow">FIRST SETUP</span>
        <h1>Создай профиль</h1>
        <p>Укажи данные своего аккаунта StandKnife.</p>

        <input placeholder="Игровой ник" value={nickname} onChange={e => setNickname(e.target.value)} />
        <input placeholder="StandKnife ID" value={gameId} onChange={e => setGameId(e.target.value)} />

        {error && <div className="error">{error}</div>}

        <button className="primary" onClick={register}>СОЗДАТЬ ПРОФИЛЬ</button>
      </div>
    );
  }

  return (
    <div className="app">
      <header>
        <div className="brand"><div className="logo mini">S</div><b>STANDKNIFE</b></div>
        <button className="ghost" onClick={() => setScreen("settings")}>⚙</button>
      </header>

      {error && <div className="error">{error}</div>}

      <main>
        {screen === "home" && (
          <>
            <section className="hero">
              <div>
                <span className="eyebrow">WELCOME BACK</span>
                <h1>{profile?.nickname}</h1>
                <p>Готов к следующему матчу?</p>
              </div>
              <div className="rank"><b>{profile?.elo}</b><small>{profile?.rank}</small></div>
            </section>

            <div className="grid">
              <button className="tile wide" onClick={() => setScreen("play")}>⚔<b>5V5 MATCHMAKING</b><small>Найти рейтинговый матч</small></button>
              <button className="tile" onClick={() => setScreen("party")}>♟<b>НАПАРНИКИ</b><small>Собрать команду</small></button>
              <button className="tile" onClick={() => setScreen("stats")}>◈<b>СТАТИСТИКА</b><small>Результаты</small></button>
              <button className="tile" onClick={() => setScreen("search")}>⌕<b>ИГРОКИ</b><small>Найти игрока</small></button>
            </div>

            <section className="card">
              <div className="row"><span>Рейтинг</span><b>{profile?.elo} ELO</b></div>
              <div className="bar"><i style={{ width: `${Math.min(100, ((profile?.elo || 1000) % 200) / 2)}%` }} /></div>
            </section>

            <div className="stats">
              <Stat title="WINRATE" value={`${stats?.winrate || 0}%`} />
              <Stat title="K/D" value={`${stats?.kd || 0}`} />
              <Stat title="WINS" value={`${stats?.wins || 0}`} />
              <Stat title="GAMES" value={`${stats?.games || 0}`} />
            </div>
          </>
        )}

        {screen === "play" && (
          <Page title="Рейтинговый матч" subtitle="5v5 • Ranked • EU" back={() => setScreen("home")}>
            <div className="queue">
              <div className={`radar ${queue ? "on" : ""}`} />
              <span className="eyebrow">{queue ? "ПОИСК ИГРОКОВ" : "ГОТОВ К ПОИСКУ"}</span>
              <strong>{String(Math.floor(queueTime / 60)).padStart(2, "0")}:{String(queueTime % 60).padStart(2, "0")}</strong>
              <p>{queue ? "Подбираем игроков по ELO" : `Твой рейтинг: ${profile?.elo}`}</p>
              {queue
                ? <button className="danger" onClick={leaveQueue}>ОТМЕНИТЬ ПОИСК</button>
                : <button className="primary" onClick={joinQueue}>НАЙТИ МАТЧ</button>}
            </div>
          </Page>
        )}

        {screen === "party" && (
          <Page title="Напарники" subtitle="Собери команду перед матчем." back={() => setScreen("home")}>
            <div className="card">
              {[1,2,3,4,5].map(i => (
                <div className="party-slot" key={i}>
                  <div className="avatar">{i === 1 ? profile?.nickname?.[0] : "+"}</div>
                  <span>{i === 1 ? profile?.nickname : "Свободно"}</span>
                </div>
              ))}
              <button className="primary" onClick={() => setScreen("search")}>ПРИГЛАСИТЬ ИГРОКА</button>
            </div>
          </Page>
        )}

        {screen === "profile" && (
          <Page title="Профиль" subtitle={`ID: ${profile?.game_id}`} back={() => setScreen("home")}>
            <div className="profile">
              <div className="big-avatar">{profile?.nickname?.[0]}</div>
              <h2>{profile?.nickname}</h2>
              <span className="eyebrow">{profile?.rank}</span>
              <strong className="elo">{profile?.elo}</strong>
            </div>
            <div className="stats">
              <Stat title="WINS" value={`${profile?.wins}`} />
              <Stat title="LOSSES" value={`${profile?.losses}`} />
              <Stat title="KILLS" value={`${profile?.kills}`} />
              <Stat title="DEATHS" value={`${profile?.deaths}`} />
            </div>
          </Page>
        )}

        {screen === "stats" && (
          <Page title="Статистика" subtitle="Твои соревновательные показатели." back={() => setScreen("home")}>
            <div className="stats">
              <Stat title="WINRATE" value={`${stats?.winrate}%`} />
              <Stat title="K/D" value={`${stats?.kd}`} />
              <Stat title="GAMES" value={`${stats?.games}`} />
              <Stat title="ELO" value={`${stats?.elo}`} />
            </div>
          </Page>
        )}

        {screen === "search" && (
          <Page title="Поиск игроков" subtitle="Найди напарника по нику." back={() => setScreen("home")}>
            <input placeholder="Ник игрока..." value={search} onChange={e => searchPlayers(e.target.value)} />
            {players.map(p => (
              <div className="player" key={p.game_id}>
                <div className="avatar">{p.nickname[0]}</div>
                <div><b>{p.nickname}</b><small>{p.rank} • {p.elo} ELO</small></div>
              </div>
            ))}
          </Page>
        )}

        {screen === "settings" && (
          <Page title="Настройки" subtitle="Параметры платформы." back={() => setScreen("home")}>
            <div className="card">
              <Info a="Регион" b="EU" />
              <Info a="Язык" b="Русский" />
              <Info a="Уведомления" b="Включены" />
              <Info a="Версия" b="1.0.0" />
            </div>
          </Page>
        )}

        {screen === "premium" && (
          <Page title="Premium" subtitle="Расширенные возможности." back={() => setScreen("home")}>
            <div className="premium">
              <span className="premium-icon">◆</span>
              <h2>STANDKNIFE PREMIUM</h2>
              <p>Расширенная статистика, Premium-профиль и дополнительные возможности.</p>
              <button className="primary">ПОДКЛЮЧИТЬ PREMIUM</button>
            </div>
          </Page>
        )}
      </main>

      <nav>
        <Nav t="⌂" n="Главная" a={screen === "home"} c={() => setScreen("home")} />
        <Nav t="⚔" n="Играть" a={screen === "play"} c={() => setScreen("play")} />
        <Nav t="♟" n="Пати" a={screen === "party"} c={() => setScreen("party")} />
        <Nav t="◉" n="Профиль" a={screen === "profile"} c={() => setScreen("profile")} />
        <Nav t="◆" n="Premium" a={screen === "premium"} c={() => setScreen("premium")} />
      </nav>
    </div>
  );
}

function Page({ title, subtitle, back, children }: any) {
  return <section><button className="back" onClick={back}>← Назад</button><span className="eyebrow">STANDKNIFE</span><h1>{title}</h1><p>{subtitle}</p>{children}</section>;
}

function Stat({ title, value }: any) {
  return <div className="stat"><small>{title}</small><b>{value}</b></div>;
}

function Info({ a, b }: any) {
  return <div className="row info"><span>{a}</span><b>{b}</b></div>;
}

function Nav({ t, n, a, c }: any) {
  return <button className={a ? "nav active" : "nav"} onClick={c}><span>{t}</span><small>{n}</small></button>;
}
