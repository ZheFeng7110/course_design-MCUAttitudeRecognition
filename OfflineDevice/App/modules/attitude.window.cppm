//! 定长环形窗口缓冲：每收满 kWindowStride 新帧，可供取一次最新 kWindowLen 帧快照

module;

#include <cstdint>

export module attitude.window;

import attitude.config;

export namespace attitude {

class WindowBuffer {
public:
    void reset() noexcept
    {
        head_ = 0;
        count_ = 0;
        since_last_ = 0;
    }

    void push(const ImuFrame& frame) noexcept
    {
        ring_[head_] = frame;
        head_ = (head_ + 1) % kWindowLen;
        if (count_ < kWindowLen) ++count_;
        ++since_last_;
    }

    /// 窗口已满且自上次快照已累计 kWindowStride 新帧
    bool ready() const noexcept
    {
        return count_ >= kWindowLen && since_last_ >= kWindowStride;
    }

    /// 线性化拷贝最新 kWindowLen 帧（时间升序）到 out（调用方局部缓冲，
    /// 避免推理期间丢样），然后重置步进计数。
    void takeSnapshot(ImuFrame* out) noexcept
    {
        const int start = (head_ - count_ + kWindowLen) % kWindowLen;
        for (int i = 0; i < count_; ++i) {
            out[i] = ring_[(start + i) % kWindowLen];
        }
        since_last_ = 0;
    }

private:
    ImuFrame ring_[kWindowLen]{};
    int head_ = 0;
    int count_ = 0;
    int since_last_ = 0;
};

}  // namespace attitude
