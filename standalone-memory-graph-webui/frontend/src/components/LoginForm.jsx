import React, { useState, useCallback, useEffect, useRef } from 'react';
import { motion } from 'framer-motion';
import { LayoutGrid, User, Lock, Loader2, AlertCircle } from 'lucide-react';
import { login } from '../lib/api';
import { useI18n } from '../lib/i18n';

// 神经网络星空背景组件
const NeuralStarfield = () => {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;

    const resize = () => {
      canvas.width = window.innerWidth * dpr;
      canvas.height = window.innerHeight * dpr;
      canvas.style.width = `${window.innerWidth}px`;
      canvas.style.height = `${window.innerHeight}px`;
      ctx.scale(dpr, dpr);
    };
    resize();
    window.addEventListener('resize', resize);

    // 神经元节点
    class NeuralNode {
      constructor() {
        this.x = Math.random() * window.innerWidth;
        this.y = Math.random() * window.innerHeight;
        this.vx = (Math.random() - 0.5) * 0.3;
        this.vy = (Math.random() - 0.5) * 0.3;
        this.radius = Math.random() * 2 + 1;
        this.pulsePhase = Math.random() * Math.PI * 2;
        this.pulseSpeed = Math.random() * 0.02 + 0.01;
        this.energy = Math.random();
      }

      update() {
        this.x += this.vx;
        this.y += this.vy;

        if (this.x < 0 || this.x > window.innerWidth) this.vx *= -1;
        if (this.y < 0 || this.y > window.innerHeight) this.vy *= -1;

        this.pulsePhase += this.pulseSpeed;
        this.energy = Math.sin(this.pulsePhase) * 0.5 + 0.5;
      }

      draw(ctx) {
        const intensity = this.energy;
        const gradient = ctx.createRadialGradient(this.x, this.y, 0, this.x, this.y, this.radius * 3);
        gradient.addColorStop(0, `rgba(99, 102, 241, ${0.8 * intensity})`);
        gradient.addColorStop(0.5, `rgba(139, 92, 246, ${0.3 * intensity})`);
        gradient.addColorStop(1, 'rgba(99, 102, 241, 0)');

        ctx.fillStyle = gradient;
        ctx.beginPath();
        ctx.arc(this.x, this.y, this.radius * 3, 0, Math.PI * 2);
        ctx.fill();

        ctx.fillStyle = `rgba(199, 210, 254, ${0.9 * intensity})`;
        ctx.beginPath();
        ctx.arc(this.x, this.y, this.radius, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    // 星星
    class Star {
      constructor() {
        this.x = Math.random() * window.innerWidth;
        this.y = Math.random() * window.innerHeight;
        this.radius = Math.random() * 0.8 + 0.2;
        this.opacity = Math.random() * 0.5 + 0.3;
        this.twinkleSpeed = Math.random() * 0.02 + 0.01;
        this.twinklePhase = Math.random() * Math.PI * 2;
      }

      update() {
        this.twinklePhase += this.twinkleSpeed;
      }

      draw(ctx) {
        const twinkle = Math.sin(this.twinklePhase) * 0.3 + 0.7;
        ctx.fillStyle = `rgba(226, 232, 240, ${this.opacity * twinkle})`;
        ctx.beginPath();
        ctx.arc(this.x, this.y, this.radius, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    const nodes = Array.from({ length: 35 }, () => new NeuralNode());
    const stars = Array.from({ length: 200 }, () => new Star());

    const animate = () => {
      ctx.fillStyle = 'rgba(7, 11, 24, 0.05)';
      ctx.fillRect(0, 0, window.innerWidth, window.innerHeight);

      stars.forEach(star => {
        star.update();
        star.draw(ctx);
      });

      nodes.forEach(node => node.update());

      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const dx = nodes[i].x - nodes[j].x;
          const dy = nodes[i].y - nodes[j].y;
          const distance = Math.sqrt(dx * dx + dy * dy);

          if (distance < 180) {
            const opacity = (1 - distance / 180) * 0.3;
            const energy = (nodes[i].energy + nodes[j].energy) / 2;

            const gradient = ctx.createLinearGradient(
              nodes[i].x, nodes[i].y,
              nodes[j].x, nodes[j].y
            );
            gradient.addColorStop(0, `rgba(99, 102, 241, ${opacity * energy})`);
            gradient.addColorStop(0.5, `rgba(139, 92, 246, ${opacity * energy * 0.6})`);
            gradient.addColorStop(1, `rgba(99, 102, 241, ${opacity * energy})`);

            ctx.strokeStyle = gradient;
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(nodes[i].x, nodes[i].y);
            ctx.lineTo(nodes[j].x, nodes[j].y);
            ctx.stroke();
          }
        }
      }

      nodes.forEach(node => node.draw(ctx));

      requestAnimationFrame(animate);
    };

    animate();

    return () => {
      window.removeEventListener('resize', resize);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className="absolute inset-0 pointer-events-none"
      style={{ background: 'linear-gradient(to bottom, #050810, #0a0e1a, #070b18)' }}
    />
  );
};

const LoginForm = ({ onAuthenticated }) => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const { t, lang } = useI18n();

  const handleSubmit = useCallback(async (e) => {
    e.preventDefault();
    if (!username.trim() || !password) return;

    setLoading(true);
    setError('');

    try {
      await login(username.trim(), password);
      onAuthenticated();
    } catch (err) {
      if (err.response && err.response.status === 401) {
        setError(t('login.error_invalid'));
      } else {
        setError(t('login.error_connection'));
      }
    } finally {
      setLoading(false);
    }
  }, [username, password, onAuthenticated, t]);

  // 根据语言选择内容
  const features = lang === 'zh' ? [
    { title: '默认私密', desc: '用户范围审核队列和命名空间检查，确保个人记忆不进入共享核心。' },
    { title: '可审核变更', desc: '批准、拒绝、读回和回滚记忆更新，而不是信任静默写入。' },
    { title: '精心设计的召回', desc: '将对话转化为可搜索、可审计、可完善的活体外部大脑。' },
  ] : [
    { title: 'Private by default', desc: 'User-scoped review queues and namespace checks keep personal memory out of shared core.' },
    { title: 'Reviewable changes', desc: 'Approve, reject, read back, and roll back memory updates instead of trusting silent writes.' },
    { title: 'Designed recall', desc: 'Turn conversations into a living external brain that can be searched, audited, and refined.' },
  ];

  const tagline = lang === 'zh'
    ? { line1: '你的外部大脑，', line2: '变得', highlight: '可检查', suffix: '。' }
    : { line1: 'Your external brain,', line2: 'made', highlight: 'inspectable', suffix: '.' };

  const subtitle = lang === 'zh'
    ? '记忆图谱将影子写入变为冷静的审核室：只批准属于的内容，保持用户隔离，并在成为可信召回之前通过读回验证每一个重要记忆。'
    : 'Memory Graph turns shadow writes into a calm review room: approve only what belongs, keep users isolated, and verify every important memory by readback before it becomes trusted recall.';

  const loginDesc = lang === 'zh'
    ? '登录以审核记忆候选、检查命名空间，并保护外部大脑免受噪声或跨用户写入的干扰。'
    : 'Sign in to review memory candidates, inspect namespaces, and protect the external brain from noisy or cross-user writes.';

  const bottomText = lang === 'zh' ? '审核 • 读回 • 隔离' : 'Review • Readback • Isolation';

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden px-4 py-10 text-slate-100">
      {/* 神经网络星空背景 */}
      <NeuralStarfield />

      {/* 顶部装饰线 */}
      <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-indigo-500/30 to-transparent" />
      <div className="pointer-events-none absolute inset-x-0 bottom-0 h-px bg-gradient-to-r from-transparent via-purple-500/20 to-transparent" />

      <div className="relative z-10 grid w-full max-w-6xl items-center gap-8 lg:grid-cols-[1.15fr_0.85fr]">
        {/* Left Section */}
        <motion.section
          className="hidden lg:block space-y-6"
          initial={{ opacity: 0, x: -30 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.8 }}
        >
          <div className="inline-flex items-center gap-2 rounded-full border border-indigo-500/30 bg-indigo-500/5 px-4 py-2 text-xs font-medium uppercase tracking-[0.28em] text-indigo-200 backdrop-blur-xl shadow-lg shadow-indigo-500/10">
            <span className="h-1.5 w-1.5 rounded-full bg-indigo-400 shadow-[0_0_8px_rgba(99,102,241,0.8)] animate-pulse" />
            {lang === 'zh' ? '记忆审核工作台' : 'Memory Review Workbench'}
          </div>

          <h1 className="max-w-3xl text-4xl sm:text-5xl md:text-6xl font-bold tracking-tight text-white leading-tight">
            {tagline.line1}
            <br />
            {tagline.line2}{' '}
            <span className="relative inline-block">
              <span className="relative z-10 bg-gradient-to-r from-indigo-400 via-purple-400 to-cyan-400 bg-clip-text text-transparent">
                {tagline.highlight}
              </span>
              <motion.span
                className="absolute inset-0 bg-gradient-to-r from-indigo-400/20 via-purple-400/20 to-cyan-400/20 blur-xl"
                animate={{
                  opacity: [0.3, 0.6, 0.3],
                }}
                transition={{
                  duration: 3,
                  repeat: Infinity,
                  ease: "easeInOut",
                }}
              />
            </span>
            {tagline.suffix}
          </h1>

          <p className="max-w-2xl text-base sm:text-lg leading-7 sm:leading-8 text-slate-300">
            {subtitle}
          </p>

          <div className="grid max-w-3xl gap-3 pt-2">
            {features.map((item, i) => (
              <motion.div
                key={item.title}
                className="group rounded-xl border border-white/10 bg-white/[0.05] p-4 backdrop-blur-sm transition-all duration-200 hover:border-indigo-400/40 hover:bg-white/[0.08] hover:shadow-lg hover:shadow-indigo-500/10"
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5, delay: 0.2 + i * 0.1 }}
                whileHover={{ y: -2 }}
              >
                <h3 className="text-xs sm:text-sm font-bold uppercase tracking-[0.15em] text-indigo-200 mb-1.5">{item.title}</h3>
                <p className="text-xs sm:text-sm leading-5 sm:leading-6 text-slate-400">{item.desc}</p>
              </motion.div>
            ))}
          </div>
        </motion.section>

        {/* Right Section - Login Form */}
        <motion.section
          className="mx-auto w-full max-w-md"
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.6, delay: 0.2 }}
        >
          <div className="relative rounded-3xl border border-white/10 bg-slate-950/50 p-2 shadow-2xl backdrop-blur-2xl">
            <div className="absolute inset-x-10 -top-px h-px bg-gradient-to-r from-transparent via-indigo-400/60 to-transparent" />
            <div className="rounded-[1.4rem] border border-white/[0.06] bg-gradient-to-b from-white/[0.04] to-transparent p-6 sm:p-8">
              <div className="mb-6 sm:mb-8">
                <div className="mb-4 sm:mb-5 flex items-center justify-between">
                  <div className="flex h-12 w-12 items-center justify-center rounded-xl border border-indigo-400/30 bg-indigo-500/10 shadow-lg shadow-indigo-500/20">
                    <LayoutGrid className="h-6 w-6 text-indigo-300" />
                  </div>
                  <div className="rounded-full border border-emerald-400/30 bg-emerald-400/10 px-3 py-1 text-[10px] font-bold uppercase tracking-[0.22em] text-emerald-300">
                    {lang === 'zh' ? '已保护' : 'Guarded'}
                  </div>
                </div>
                <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-white">{t('login.title')}</h1>
                <p className="mt-2 text-xs sm:text-sm leading-5 sm:leading-6 text-slate-400">
                  {loginDesc}
                </p>
              </div>

              <form onSubmit={handleSubmit} className="space-y-4">
                <div>
                  <label htmlFor="username" className="mb-2 block text-xs font-bold uppercase tracking-[0.15em] text-slate-400">
                    {t('login.username')}
                  </label>
                  <div className="relative">
                    <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 sm:pl-4">
                      <User className="h-4 w-4 text-slate-500" />
                    </div>
                    <input
                      id="username"
                      type="text"
                      value={username}
                      onChange={(e) => {
                        setUsername(e.target.value);
                        if (error) setError('');
                      }}
                      placeholder={t('login.username')}
                      disabled={loading}
                      autoFocus
                      className="w-full rounded-xl sm:rounded-2xl border border-white/10 bg-slate-900/40 py-2.5 sm:py-3 pl-10 sm:pl-11 pr-3 sm:pr-4 text-sm text-slate-100 placeholder-slate-600 outline-none transition-all duration-200 focus:border-indigo-400/60 focus:bg-slate-900/60 focus:ring-2 focus:ring-indigo-500/20 disabled:opacity-50"
                    />
                  </div>
                </div>

                <div>
                  <label htmlFor="password" className="mb-2 block text-xs font-bold uppercase tracking-[0.15em] text-slate-400">
                    {t('login.password')}
                  </label>
                  <div className="relative">
                    <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 sm:pl-4">
                      <Lock className="h-4 w-4 text-slate-500" />
                    </div>
                    <input
                      id="password"
                      type="password"
                      value={password}
                      onChange={(e) => {
                        setPassword(e.target.value);
                        if (error) setError('');
                      }}
                      placeholder={t('login.password')}
                      disabled={loading}
                      className="w-full rounded-xl sm:rounded-2xl border border-white/10 bg-slate-900/40 py-2.5 sm:py-3 pl-10 sm:pl-11 pr-3 sm:pr-4 text-sm text-slate-100 placeholder-slate-600 outline-none transition-all duration-200 focus:border-indigo-400/60 focus:bg-slate-900/60 focus:ring-2 focus:ring-indigo-500/20 disabled:opacity-50"
                    />
                  </div>
                </div>

                {error && (
                  <motion.div
                    className="flex items-center gap-2 rounded-xl border border-red-400/30 bg-red-500/10 px-3 py-2 text-xs text-red-200"
                    initial={{ opacity: 0, y: -10 }}
                    animate={{ opacity: 1, y: 0 }}
                  >
                    <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                    <span>{error}</span>
                  </motion.div>
                )}

                <motion.button
                  type="submit"
                  disabled={loading || !username.trim() || !password}
                  className="group relative mt-2 flex w-full items-center justify-center gap-2 overflow-hidden rounded-xl sm:rounded-2xl bg-gradient-to-r from-indigo-500 via-purple-500 to-indigo-600 px-4 py-2.5 sm:py-3 text-sm font-bold text-white shadow-lg shadow-indigo-500/30 transition-all duration-200 hover:shadow-xl hover:shadow-indigo-500/40 active:scale-[0.98] disabled:from-slate-800 disabled:via-slate-800 disabled:to-slate-800 disabled:text-slate-500 disabled:shadow-none"
                  whileHover={{ scale: loading ? 1 : 1.02 }}
                  whileTap={{ scale: loading ? 1 : 0.98 }}
                >
                  {loading ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" />
                      {t('login.signing_in')}
                    </>
                  ) : (
                    <>
                      {t('login.sign_in')}
                      <span className="transition-transform duration-200 group-hover:translate-x-0.5">→</span>
                    </>
                  )}
                </motion.button>
              </form>
            </div>
          </div>

          <p className="mt-4 sm:mt-5 text-center text-xs font-bold uppercase tracking-[0.25em] text-slate-500">
            {bottomText}
          </p>
        </motion.section>
      </div>
    </div>
  );
};

export default LoginForm;
